"""
Ida y vuelta de los puentes contra el staging (QR-EXA-05): para cada puente (y rol) y cada fuente, compara las filas que
quedaron en la bodega con las que dice el staging, atención por atención. Cuenta las atenciones cuyo conjunto de filas
difiere. Es la comprobación que le falta a QR-EXA-03: esa solo cuenta filas y no ve una fila equivocada ni intercambiada.

Igual que `origen.py`, se escribe aparte de `etl/load/warehouse/` a propósito: del contrato solo toma qué columna del
staging alimenta cada columna del puente, y el filtrado, el orden, la secuencia, los valores por defecto y la unión de
repetidos los recalcula por su cuenta. Compara por **valor** y no por clave sustituta: cada clave de la bodega se
deshace (la "vuelta") hasta el valor de su dimensión, catálogo, fecha u hora.

Lo que el Loader aparta no se espera en la bodega: las atenciones que no están en el hecho y las filas con su fecha fuera
del calendario. Las atenciones que faltan en el hecho las cuenta QR-EXA-02 (origen.py).

Solo cuenta atenciones; no devuelve ni escribe valores del staging. Si el staging no es el de la carga se omite la
fuente: lo reporta QR-EXA-04.
"""
import pandas as pd
from sqlalchemy import Integer, Numeric, inspect, text
from sqlalchemy.engine import Connection

from etl.load.warehouse.contrato import CLAVE_ATENCION, Contrato
from etl.load.warehouse.por_contrato import PREFIJOS
from etl.load.warehouse.resolucion import NO_APLICA, SIN_DATO
from etl.load.warehouse.staging import leer_tablas
from etl.quality.comun import Resultado, columna_de, esquema_de, hecho_de, tabla_de
from etl.quality.origen import _carga_de, staging_vigente
from etl.quality.valores import _calendario, _clave_primaria

REGLA = "QR-EXA-05"
VACIO = "<vacio>"          # cómo se escribe un valor ausente al comparar (el mismo en las dos versiones)
SEPARADOR = "\x1f"         # une los atributos de una dimensión en un solo texto
SECUENCIA = "__secuencia"  # columna de trabajo con la posición de la fila dentro de su atención


def _origen(definicion: dict, fuente: str, campo: str = "origen") -> str | None:
    """'tabla.columna' del staging de una columna del contrato en una fuente, o None si la fuente no la trae."""
    return (definicion.get(campo) or {}).get(fuente)


def _origenes(contrato: Contrato, fuente: str, bloque: dict) -> set[str]:
    """Orígenes 'tabla.columna' que alimentan el bloque: los de sus columnas, sus banderas de mapeo y los atributos de
    las dimensiones que resuelve."""
    origenes = set()
    for d in bloque["columnas"].values():
        destino = contrato.tablas.get(d.get("dimension"), {})
        if d.get("resolucion") == "dimension" and destino.get("tipo") == "dimension":
            origenes |= {_origen(a, fuente) for a in destino["columnas"].values()}
        origenes |= {_origen(d, fuente), _origen(d, fuente, "mapeado")}
    origenes.discard(None)
    return origenes


def _lectura(contrato: Contrato, fuente: str) -> dict[str, list[str]]:
    """Columnas del staging que hay que leer para todos los puentes de la fuente: {tabla: [columnas]}."""
    pedidas: dict[str, set[str]] = {}
    for _, tipo, bloque in contrato.bloques():
        if tipo != "puente" or bloque["filas"][fuente] is None:
            continue
        for origen in _origenes(contrato, fuente, bloque):
            tabla, columna = origen.split(".")
            pedidas.setdefault(tabla, set()).add(columna)
        pedidas.setdefault(bloque["filas"][fuente], set()).update((bloque.get("orden") or {}).get(fuente) or [])
    return {tabla: sorted({CLAVE_ATENCION, *columnas}) for tabla, columnas in pedidas.items()}


def _texto(serie: pd.Series, tipo: str, escala: int | None = None) -> pd.Series:
    """
    Cada valor como texto comparable: 'fecha' (AAAA-MM-DD), 'numero' (redondeado a la escala de la columna) o 'texto'. Un
    valor ausente es VACIO. Así las dos versiones se comparan igual aunque una venga de pandas y otra de la base.
    """
    if tipo == "fecha":
        serie = pd.to_datetime(serie, errors="coerce").dt.strftime("%Y-%m-%d")
    elif tipo == "numero":
        serie = pd.to_numeric(serie, errors="coerce").astype(float)
        if escala is not None:
            serie = serie.round(escala)
        serie = serie.map(lambda x: None if pd.isna(x) else f"{x:.6f}")
    return serie.map(lambda x: VACIO if pd.isna(x) else str(x)).astype(object)


def _tipo_de_copia(tipos: dict, columna: str) -> tuple[str, int | None]:
    """Cómo comparar una columna copiada: número (con la escala de la base) o texto."""
    tipo = tipos[columna]
    if isinstance(tipo, (Numeric, Integer)):
        return "numero", getattr(tipo, "scale", None)
    return "texto", None


def _esperado(contrato: Contrato, fuente: str, bloque: dict, tablas: dict[str, pd.DataFrame], atenciones: set,
              limites: tuple, tipos: dict) -> pd.DataFrame:
    """
    Las filas que el staging dice que debe tener el puente, con una columna por columna del bloque (valores como texto) y
    la clave de la atención. Aplica lo mismo que la carga: solo atenciones que están en el hecho, sin las filas con su
    fecha fuera del calendario ni las que no traen ningún valor propio, en el orden del bloque, con su secuencia y sin
    repeticiones exactas cuando el puente no tiene secuencia.
    """
    tabla_filas = bloque["filas"][fuente]
    orden = (bloque.get("orden") or {}).get(fuente) or []
    origenes = _origenes(contrato, fuente, bloque)
    df = tablas[tabla_filas]
    df = df[df[CLAVE_ATENCION].isin(atenciones)]
    for d in bloque["columnas"].values():
        origen = _origen(d, fuente)
        if d.get("resolucion") == "calendario" and origen and origen.split(".")[0] == tabla_filas:
            dias = pd.to_datetime(df[origen.split(".")[1]], errors="coerce").dt.normalize()
            df = df[~((dias < limites[0]) | (dias > limites[1]))]

    propias = [o for o in origenes if o.split(".")[0] == tabla_filas]
    banderas = {_origen(d, fuente, "mapeado") for d in bloque["columnas"].values()} - {None}
    filas = df[[CLAVE_ATENCION, *orden]].copy()
    for origen in propias:
        filas[origen] = df[origen.split(".")[1]]
    valores = [o for o in propias if o not in banderas]
    filas = filas[filas[valores].notna().any(axis=1)]
    for tabla in {o.split(".")[0] for o in origenes} - {tabla_filas}:
        consulta = tablas[tabla]
        consultada = consulta[[CLAVE_ATENCION]].copy()
        for origen in (o for o in origenes if o.split(".")[0] == tabla):
            consultada[origen] = consulta[origen.split(".")[1]]
        filas = filas.merge(consultada, on=CLAVE_ATENCION, how="left")
    if orden:
        filas = filas.sort_values([CLAVE_ATENCION, *orden], kind="stable", na_position="last")
    filas[SECUENCIA] = filas.groupby(CLAVE_ATENCION, sort=False).cumcount() + 1

    sin_valor = pd.Series(None, index=filas.index, dtype=object)
    resuelto = pd.DataFrame({CLAVE_ATENCION: filas[CLAVE_ATENCION]})
    for columna, d in bloque["columnas"].items():
        resolucion, origen = d.get("resolucion", "copia"), _origen(d, fuente)
        if resolucion == "secuencia":
            resuelto[columna] = _texto(filas[SECUENCIA], "numero")
        elif resolucion == "copia":
            resuelto[columna] = _texto(filas[origen] if origen else sin_valor, *_tipo_de_copia(tipos, columna))
        elif resolucion == "calendario":
            resuelto[columna] = _texto(filas[origen] if origen else sin_valor, "fecha")
        elif resolucion == "horario":
            instantes = pd.to_datetime(filas[origen] if origen else sin_valor, errors="coerce")
            resuelto[columna] = _texto(instantes.dt.hour * 60 + instantes.dt.minute, "numero")
        elif resolucion == "texto_sin_mapeo":
            fuente_texto = bloque["columnas"][d["de"]]
            valor, bandera = _origen(fuente_texto, fuente), _origen(fuente_texto, fuente, "mapeado")
            if valor and bandera:
                no_mapeado = filas[valor].notna() & ~filas[bandera].fillna(False).astype(bool)
                resuelto[columna] = _texto(filas[valor].astype(object).where(no_mapeado, None), "texto")
            else:
                resuelto[columna] = _texto(sin_valor, "texto")
        else:
            resuelto[columna] = _valor_de_dimension(contrato, fuente, d, filas, sin_valor)
    if not any(d.get("resolucion") == "secuencia" for d in bloque["columnas"].values()):
        resuelto = resuelto.drop_duplicates()
    return resuelto.reset_index(drop=True)


def _valor_de_dimension(contrato: Contrato, fuente: str, d: dict, filas: pd.DataFrame, sin_valor: pd.Series
                        ) -> pd.Series:
    """El valor que debe tener una columna que apunta a una dimensión o a un catálogo, con los miembros por defecto."""
    destino = contrato.tablas[d["dimension"]]
    if destino["tipo"] == "dimension":
        atributos = pd.concat([filas[_origen(a, fuente)] if _origen(a, fuente) else sin_valor
                               for a in destino["columnas"].values()], axis=1)
        vacia = atributos.isna().all(axis=1)
        atributos = atributos.astype(object).where(atributos.notna(), SIN_DATO)
        if destino.get("vacio") == "no_aplica":
            atributos.loc[vacia] = NO_APLICA
        if atributos.empty:
            return pd.Series(dtype=object)
        return atributos.astype(str).apply(SEPARADOR.join, axis=1)
    origen, bandera = _origen(d, fuente), _origen(d, fuente, "mapeado")
    valores = filas[origen].astype(object) if origen else sin_valor
    if bandera:
        no_mapeado = valores.notna() & ~filas[bandera].fillna(False).astype(bool)
        valores = valores.where(~no_mapeado, destino["sin_mapeo"])
    return _texto(valores.where(valores.notna(), SIN_DATO), "texto")


def _obtenido(conexion: Connection, contrato: Contrato, fuente: str, nombre: str, bloque: dict, tipos: dict
              ) -> pd.DataFrame:
    """
    Las filas del puente de la fuente en la bodega, con cada clave deshecha hasta su valor (la fecha, el minuto del día,
    el atributo de la dimensión o el texto del catálogo), en las mismas columnas y como texto que `_esperado`.
    """
    esquema = esquema_de(contrato)
    inspector = inspect(conexion)
    hecho, _ = hecho_de(contrato)
    clave_hecho = _clave_primaria(inspector, esquema, hecho)
    puente, _, rol = nombre.partition("[")
    q = lambda c: columna_de(conexion, c)   # noqa: E731
    seleccion, uniones, dimensiones = [f"h.{q(CLAVE_ATENCION)} AS {q(CLAVE_ATENCION)}"], [], {}
    for i, (columna, d) in enumerate(bloque["columnas"].items()):
        resolucion, alias = d.get("resolucion", "copia"), f"j{i}"
        if resolucion in ("copia", "secuencia", "texto_sin_mapeo"):
            seleccion.append(f"b.{q(columna)} AS {q(columna)}")
        elif resolucion == "calendario":
            tabla, fecha = _calendario(contrato)
            uniones.append(f"LEFT JOIN {tabla_de(conexion, esquema, tabla)} {alias} ON "
                           f"{alias}.{q(_clave_primaria(inspector, esquema, tabla))} = b.{q(columna)}")
            seleccion.append(f"{alias}.{q(fecha)} AS {q(columna)}")
        elif resolucion == "horario":
            (tabla,) = [t for t, x in contrato.tablas.items() if x["tipo"] == "horario"]
            nombres = {x["generado"]: c for c, x in contrato.tablas[tabla]["columnas"].items()}
            uniones.append(f"LEFT JOIN {tabla_de(conexion, esquema, tabla)} {alias} ON "
                           f"{alias}.{q(_clave_primaria(inspector, esquema, tabla))} = b.{q(columna)}")
            seleccion.append(f"{alias}.{q(nombres['hora'])} * 60 + {alias}.{q(nombres['minuto'])} AS {q(columna)}")
        else:
            destino, tabla = contrato.tablas[d["dimension"]], d["dimension"]
            uniones.append(f"LEFT JOIN {tabla_de(conexion, esquema, tabla)} {alias} ON "
                           f"{alias}.{q(_clave_primaria(inspector, esquema, tabla))} = b.{q(columna)}")
            atributos = list(destino["columnas"]) if destino["tipo"] == "dimension" else [destino["columna"]]
            dimensiones[columna] = [f"{columna}__{a}" for a in atributos]
            seleccion += [f"{alias}.{q(a)} AS {q(f'{columna}__{a}')}" for a in atributos]
    filas = conexion.execute(text(
        f"SELECT {', '.join(seleccion)} FROM {tabla_de(conexion, esquema, puente)} b "
        f"JOIN {tabla_de(conexion, esquema, hecho)} h ON h.{q(clave_hecho)} = b.{q(clave_hecho)} "
        + " ".join(uniones) + f" WHERE h.{q(CLAVE_ATENCION)} LIKE :prefijo" + (" AND b.rol = :rol" if rol else "")
    ), {"prefijo": f"{PREFIJOS[fuente]}-%", **({"rol": rol.rstrip("]")} if rol else {})}).mappings().all()
    bruto = pd.DataFrame([dict(f) for f in filas], columns=_columnas(seleccion))

    resuelto = pd.DataFrame({CLAVE_ATENCION: bruto[CLAVE_ATENCION]})
    for columna, d in bloque["columnas"].items():
        resolucion = d.get("resolucion", "copia")
        if columna in dimensiones:
            partes = bruto[dimensiones[columna]].astype(object)
            partes = partes.where(partes.notna(), VACIO)
            resuelto[columna] = (partes.astype(str).apply(SEPARADOR.join, axis=1) if len(partes)
                                 else pd.Series(dtype=object))
        elif resolucion == "calendario":
            resuelto[columna] = _texto(bruto[columna], "fecha")
        elif resolucion in ("horario", "secuencia"):
            resuelto[columna] = _texto(bruto[columna], "numero")
        elif resolucion == "copia":
            resuelto[columna] = _texto(bruto[columna], *_tipo_de_copia(tipos, columna))
        else:
            resuelto[columna] = _texto(bruto[columna], "texto")
    return resuelto.reset_index(drop=True)


def _columnas(seleccion: list[str]) -> list[str]:
    """Nombres de las columnas de una consulta sin filas, tomados de sus alias ('... AS nombre')."""
    return [s.rsplit(" AS ", 1)[1].strip('"') for s in seleccion]


def _atenciones_distintas(esperado: pd.DataFrame, obtenido: pd.DataFrame) -> tuple[int, int]:
    """
    (atenciones con filas en alguna de las dos versiones, atenciones cuyo conjunto de filas difiere). Se suma +1 por cada
    fila esperada y −1 por cada obtenida: lo que no queda en cero es una fila que está en una y no en la otra.
    """
    columnas = list(esperado.columns)
    todo = pd.concat([esperado.assign(_lado=1), obtenido[columnas].assign(_lado=-1)], ignore_index=True)
    if todo.empty:
        return 0, 0
    neto = todo.groupby(columnas)["_lado"].sum()
    return int(todo[CLAVE_ATENCION].nunique()), int(neto[neto != 0].index.get_level_values(0).nunique())


def verificar_puentes_contra_staging(conexion: Connection, contrato: Contrato, staging_dirs: dict[str, str]
                                     ) -> list[Resultado]:
    """
    QR-EXA-05 (si incumple, la carga construyó mal las filas de un puente), por puente (y rol) y fuente con carga exitosa y
    staging vigente: evaluadas = atenciones que tienen filas en el staging o en la bodega; incumplen = atenciones cuyo
    conjunto de filas (con sus valores, secuencia, fechas y horas) no es el del staging.
    """
    esquema = esquema_de(contrato)
    hecho, _ = hecho_de(contrato)
    calendario, fecha = _calendario(contrato)
    resultados = []
    for fuente, run_id in _carga_de(conexion, contrato).items():
        carpeta = staging_dirs.get(fuente)
        if not staging_vigente(carpeta, run_id):
            continue
        tablas = leer_tablas(carpeta, _lectura(contrato, fuente))
        atenciones = {c for (c,) in conexion.execute(text(
            f"SELECT {columna_de(conexion, CLAVE_ATENCION)} FROM {tabla_de(conexion, esquema, hecho)} "
            f"WHERE {columna_de(conexion, CLAVE_ATENCION)} LIKE :prefijo"), {"prefijo": f"{PREFIJOS[fuente]}-%"})}
        desde, hasta = conexion.execute(text(
            f"SELECT min({columna_de(conexion, fecha)}), max({columna_de(conexion, fecha)}) "
            f"FROM {tabla_de(conexion, esquema, calendario)}")).one()
        limites = (pd.Timestamp(desde), pd.Timestamp(hasta))
        for nombre, tipo, bloque in contrato.bloques():
            if tipo != "puente" or bloque["filas"][fuente] is None:
                continue
            puente = nombre.partition("[")[0]
            tipos = {c["name"]: c["type"] for c in inspect(conexion).get_columns(puente, schema=esquema)}
            esperado = _esperado(contrato, fuente, bloque, tablas, atenciones, limites, tipos)
            obtenido = _obtenido(conexion, contrato, fuente, nombre, bloque, tipos)
            evaluadas, distintas = _atenciones_distintas(esperado, obtenido)
            resultados.append(Resultado(REGLA, f"{nombre} ({fuente}): atenciones con filas distintas al staging",
                                        evaluadas, distintas))
    return resultados
