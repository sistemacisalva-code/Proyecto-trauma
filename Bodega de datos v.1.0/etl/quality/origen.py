"""
Ida y vuelta de la bodega contra el staging (QR-EXA-04 y QR-EXA-02): compara, atención por atención y celda por celda, lo que quedó
en el hecho con lo que dice el staging de la carga. Responde la pregunta que las demás reglas no responden: si la carga
se equivocó al construir una fila, la bitácora y la bodega coincidirían igual; el staging no.

Se escribe aparte de `etl/load/warehouse/resolucion.py` a propósito: solo toma del contrato qué columna del staging
alimenta cada columna del hecho, y la primera toma y la comparación las calcula por su cuenta. Si el Loader y esta
verificación compartieran el código, un error de lectura del staging pasaría las dos.

Alcance: las columnas del hecho que se copian del staging (medidas, identificador y texto), sus fechas (se compara el
día contra `dim_tiempo`), la hora de alta (se compara la hora y el minuto contra `dim_horario`) y los atributos de las
dimensiones (se compara cada atributo del miembro al que apunta la atención con lo que dice el staging, con los
miembros por defecto 'Sin dato' y 'No aplica' calculados aparte de `resolucion.py`). Los puentes son QR-EXA-05
(`puentes.py`). Una comparación celda a celda de las medidas implica que su conteo, suma y promedio coinciden, así que
no hace falta una regla aparte (QR-EXA-06).

Solo cuenta atenciones y celdas; no devuelve ni escribe valores del staging.
"""
import numpy as np
import pandas as pd
from sqlalchemy import Integer, Numeric, String, Text, inspect, text
from sqlalchemy.engine import Connection

from etl.load.warehouse.contrato import CLAVE_ATENCION, Contrato
from etl.load.warehouse.por_contrato import PREFIJOS
from etl.load.warehouse.resolucion import NO_APLICA, SIN_DATO
from etl.load.warehouse.staging import leer_manifiesto, leer_tablas
from etl.quality.comun import Resultado, columna_de, esquema_de, hecho_de, tabla_de
from etl.quality.valores import _calendario, _clave_primaria

REGLA = "QR-EXA-04"
REGLA_ATENCIONES = "QR-EXA-02"


def _origen(definicion: dict, fuente: str) -> str | None:
    """'tabla.columna' del staging de una columna del contrato en una fuente, o None si la fuente no la trae."""
    return (definicion.get("origen") or {}).get(fuente)


def _columnas_comparables(hecho: dict) -> dict[str, dict]:
    """Columnas del hecho que se copian del staging o son fechas del calendario (no las claves de dimensión ni la
    llave de la atención, que es con lo que se unen los dos lados)."""
    return {nombre: d for nombre, d in hecho["columnas"].items()
            if nombre != CLAVE_ATENCION and d.get("resolucion") in (None, "copia", "calendario")}


def _primera_toma(df: pd.DataFrame, orden: list[str]) -> pd.DataFrame:
    """
    Por atención, la primera fila con algún valor, ordenando por `orden` (vacíos al final; en empate, el orden del
    staging). Es la misma regla del contrato, escrita de otra forma: ordenar y quedarse con la cabeza de cada grupo.
    """
    valores = [c for c in df.columns if c != CLAVE_ATENCION and c not in orden]
    con_valor = df[df[valores].notna().any(axis=1)]
    if orden:
        con_valor = con_valor.sort_values(orden, kind="stable", na_position="last")
    return con_valor.groupby(CLAVE_ATENCION, sort=False).head(1)


def _esperado(contrato: Contrato, fuente: str, columnas: dict[str, dict], staging_dir: str) -> pd.DataFrame:
    """Lo que el staging dice de cada columna del hecho: una fila por atención, indexada por la clave."""
    hecho, definicion = hecho_de(contrato)
    declaradas = contrato.staging[fuente]
    pedidas: dict[str, set[str]] = {definicion["filas"][fuente]: {CLAVE_ATENCION}}
    for d in columnas.values():
        if _origen(d, fuente):
            tabla, columna = _origen(d, fuente).split(".")
            pedidas.setdefault(tabla, {CLAVE_ATENCION}).update({columna, *(declaradas[tabla].get("orden") or [])})
    tablas = leer_tablas(staging_dir, {t: sorted(c) for t, c in pedidas.items()})

    base = tablas[definicion["filas"][fuente]].set_index(CLAVE_ATENCION)
    esperado = pd.DataFrame(index=base.index)
    for nombre, d in columnas.items():
        origen = _origen(d, fuente)
        if not origen:
            esperado[nombre] = None
            continue
        tabla, columna = origen.split(".")
        df = tablas[tabla]
        if declaradas[tabla]["grano"] == "varias":
            df = _primera_toma(df, declaradas[tabla].get("orden") or [])
        esperado[nombre] = df.set_index(CLAVE_ATENCION)[columna].reindex(esperado.index)
    return esperado


def _obtenido(conexion: Connection, contrato: Contrato, fuente: str, columnas: dict[str, dict]) -> pd.DataFrame:
    """Lo que quedó en el hecho de la fuente, con las fechas ya traducidas de `dim_tiempo` al día."""
    esquema = esquema_de(contrato)
    hecho, _ = hecho_de(contrato)
    seleccion = ", ".join(columna_de(conexion, c) for c in [CLAVE_ATENCION, *columnas])
    filas = conexion.execute(
        text(f"SELECT {seleccion} FROM {tabla_de(conexion, esquema, hecho)} WHERE {columna_de(conexion, CLAVE_ATENCION)} "
             f"LIKE :prefijo"), {"prefijo": PREFIJOS[fuente] + "-%"}).all()
    obtenido = pd.DataFrame(filas, columns=[CLAVE_ATENCION, *columnas]).set_index(CLAVE_ATENCION)

    calendario, fecha = _calendario(contrato)
    clave = _clave_primaria(inspect(conexion), esquema, calendario)
    dias = dict(conexion.execute(text(
        f"SELECT {columna_de(conexion, clave)}, {columna_de(conexion, fecha)} FROM {tabla_de(conexion, esquema, calendario)}"
    )).all())
    for nombre, d in columnas.items():
        if d.get("resolucion") == "calendario":
            obtenido[nombre] = pd.to_datetime(obtenido[nombre].map(dias))
    return obtenido


def _distintas(esperado: pd.Series, obtenido: pd.Series, tipo, es_fecha: bool) -> pd.Series:
    """
    Celdas donde el staging y la bodega no coinciden. Dos vacíos coinciden; un vacío y un valor, no. Los números se
    comparan con la escala de la columna (la base redondea al guardar); las fechas, por día.
    """
    if es_fecha:
        esperado = pd.to_datetime(esperado, errors="coerce").dt.normalize()
        obtenido = pd.to_datetime(obtenido, errors="coerce")
        iguales = esperado == obtenido
    elif isinstance(tipo, (Numeric, Integer)):
        esperado = pd.to_numeric(esperado, errors="coerce").astype(float)
        obtenido = pd.to_numeric(obtenido, errors="coerce").astype(float)
        if getattr(tipo, "scale", None) is not None:
            esperado = esperado.round(tipo.scale)
        iguales = pd.Series(np.isclose(esperado, obtenido, rtol=1e-6, atol=1e-9), index=esperado.index)
    else:
        iguales = esperado.astype(str) == obtenido.astype(str)
    vacios = esperado.isna() & obtenido.isna()
    llenos = esperado.notna() & obtenido.notna()
    return ~(vacios | (llenos & iguales))


def _con_miembros_por_defecto(valores: pd.DataFrame, texto: set[str], vacio: str) -> pd.DataFrame:
    """
    Los atributos de una dimensión tal como deben quedar en la bodega según el contrato, escrito aparte del
    Loader: un atributo de texto vacío es 'Sin dato'; si todos los atributos de la atención están vacíos, cada atributo de
    texto es 'No aplica' (`vacio: no_aplica`) o 'Sin dato'. Un atributo que no es de texto queda vacío.
    """
    resultado = valores.copy()
    sin_nada = valores.isna().all(axis=1)
    for columna in valores.columns:
        if columna not in texto:
            continue
        resultado[columna] = valores[columna].where(valores[columna].notna(), SIN_DATO)
        resultado.loc[sin_nada, columna] = NO_APLICA if vacio == "no_aplica" else SIN_DATO
    return resultado


def _atributos_pedidos(dimensiones: dict[str, tuple[str, dict]]) -> dict[str, dict]:
    """Los atributos de las dimensiones como columnas del staging con el nombre 'dimensión.atributo'."""
    return {f"{dim}.{a}": ad for dim, (_, d) in dimensiones.items() for a, ad in d["columnas"].items()}


def _dimensiones_del_hecho(contrato: Contrato, hecho: dict) -> dict[str, tuple[str, dict]]:
    """{dimensión: (columna del hecho que la apunta, su definición)} de las dimensiones con atributos (no catálogos)."""
    return {d["dimension"]: (nombre, contrato.tablas[d["dimension"]]) for nombre, d in hecho["columnas"].items()
            if d.get("resolucion") == "dimension" and contrato.tablas[d["dimension"]]["tipo"] == "dimension"}


def _verificar_horas(conexion: Connection, contrato: Contrato, fuente: str, columnas: list[str],
                     crudo: pd.DataFrame, comunes: pd.Index) -> list[Resultado]:
    """Una verificación por columna de hora del hecho: hora y minuto de `dim_horario` contra los del staging."""
    esquema = esquema_de(contrato)
    hecho, _ = hecho_de(contrato)
    ((horario, definicion),) = [(t, d) for t, d in contrato.tablas.items() if d["tipo"] == "horario"]
    nombres = {d["generado"]: c for c, d in definicion["columnas"].items()}
    clave = _clave_primaria(inspect(conexion), esquema, horario)
    esperado = crudo.reindex(comunes)
    resultados = []
    for nombre in columnas:
        instante = pd.to_datetime(esperado[nombre], errors="coerce")
        minutos = instante.dt.hour * 60 + instante.dt.minute
        filas = conexion.execute(text(
            f"SELECT f.{columna_de(conexion, CLAVE_ATENCION)}, "
            f"h.{columna_de(conexion, nombres['hora'])} * 60 + h.{columna_de(conexion, nombres['minuto'])} "
            f"FROM {tabla_de(conexion, esquema, hecho)} f LEFT JOIN {tabla_de(conexion, esquema, horario)} h "
            f"ON h.{columna_de(conexion, clave)} = f.{columna_de(conexion, nombre)} "
            f"WHERE f.{columna_de(conexion, CLAVE_ATENCION)} LIKE :prefijo"), {"prefijo": PREFIJOS[fuente] + "-%"}).all()
        obtenido = pd.Series(dict(filas), dtype=object).reindex(comunes).astype(float)
        distintas = int(_distintas(minutos, obtenido, Integer(), False).sum())
        resultados.append(Resultado(REGLA, f"{fuente}: {hecho}.{nombre} contra el staging (hora y minuto)",
                                    len(comunes), distintas))
    return resultados


def _verificar_atributos(conexion: Connection, contrato: Contrato, fuente: str, dimensiones: dict[str, tuple[str, dict]],
                         crudo: pd.DataFrame, comunes: pd.Index) -> list[Resultado]:
    """
    Los atributos de cada dimensión del hecho: lo que tiene el miembro al que apunta cada atención contra lo que dice el
    staging, con los miembros por defecto. Una verificación en total y una por atributo que difiere.
    """
    esquema = esquema_de(contrato)
    hecho, _ = hecho_de(contrato)
    inspector = inspect(conexion)
    crudo = crudo.reindex(comunes)
    por_atributo, total_atributos = {}, 0
    for dim, (columna_hecho, definicion) in dimensiones.items():
        atributos = list(definicion["columnas"])
        tipos = {c["name"]: c["type"] for c in inspector.get_columns(dim, schema=esquema)}
        texto = {a for a in atributos if isinstance(tipos[a], (Text, String))}
        esperado = _con_miembros_por_defecto(
            pd.DataFrame({a: crudo[f"{dim}.{a}"] for a in atributos}), texto, definicion.get("vacio", "sin_dato"))
        clave = _clave_primaria(inspector, esquema, dim)
        columnas_dim = ", ".join("d." + columna_de(conexion, a) for a in atributos)
        filas = conexion.execute(text(
            f"SELECT f.{columna_de(conexion, CLAVE_ATENCION)}, {columnas_dim} "
            f"FROM {tabla_de(conexion, esquema, hecho)} f LEFT JOIN {tabla_de(conexion, esquema, dim)} d "
            f"ON d.{columna_de(conexion, clave)} = f.{columna_de(conexion, columna_hecho)} "
            f"WHERE f.{columna_de(conexion, CLAVE_ATENCION)} LIKE :prefijo"), {"prefijo": PREFIJOS[fuente] + "-%"}).all()
        obtenido = pd.DataFrame(filas, columns=[CLAVE_ATENCION, *atributos]).set_index(CLAVE_ATENCION).reindex(comunes)
        for a in atributos:
            total_atributos += 1
            n = int(_distintas(esperado[a], obtenido[a], tipos[a], False).sum())
            if n:
                por_atributo[f"{dim}.{a}"] = n
    resultados = [Resultado(REGLA, f"{fuente}: atributos de las dimensiones contra el staging ({total_atributos} atributos)",
                            len(comunes) * total_atributos, sum(por_atributo.values()))]
    return resultados + [Resultado(REGLA, f"{fuente}: {nombre} contra el staging", len(comunes), n)
                         for nombre, n in por_atributo.items()]


def _carga_de(conexion: Connection, contrato: Contrato) -> dict[str, str]:
    """El staging (run_id) de la última carga exitosa de cada fuente: {fuente: run_id_staging}."""
    return dict(conexion.execute(
        text("SELECT DISTINCT ON (fuente) fuente, run_id_staging FROM etl_control.carga "
             "WHERE modelo = :modelo AND exitosa ORDER BY fuente, id DESC"), {"modelo": contrato.modelo}).all())


def _atenciones_apartadas(conexion: Connection, contrato: Contrato, fuente: str, tabla: str) -> int:
    """Filas de la tabla de staging que la última carga exitosa de la fuente apartó a cuarentena, según su detalle."""
    return conexion.execute(text(
        "SELECT coalesce(max(d.cuarentena), 0) FROM etl_control.carga_detalle d WHERE d.tabla_staging = :tabla AND "
        "d.carga_id = (SELECT id FROM etl_control.carga WHERE modelo = :modelo AND fuente = :fuente AND exitosa "
        "ORDER BY id DESC LIMIT 1)"), {"tabla": tabla, "modelo": contrato.modelo, "fuente": fuente}).scalar_one()


def staging_vigente(carpeta: str | None, run_id: str) -> bool:
    """El staging de la carpeta es el de la carga: existe, su manifiesto es válido y trae el `run_id` de la bitácora."""
    try:
        return leer_manifiesto(carpeta)["run_id"] == run_id if carpeta else False
    except (FileNotFoundError, ValueError):
        return False


def verificar_hecho_contra_staging(conexion: Connection, contrato: Contrato, staging_dirs: dict[str, str]
                                   ) -> list[Resultado]:
    """
    QR-EXA-04, por cada fuente con carga exitosa. Si alguna verificación incumple, el reporte la marca "Falla" y el
    veredicto queda Rechazada: la bodega no dice lo mismo que su staging, es decir, la carga construyó mal una fila
    (no es un defecto de la fuente, que solo advertiría).
      - El staging que se compara es el de la carga: su manifiesto tiene el `run_id` que quedó en la bitácora
        (evaluadas 1; incumple si falta la carpeta, el manifiesto o el run_id es otro).
      - Atenciones de la bodega que no están en el staging (evaluadas = atenciones de la fuente en el hecho).
      - Celdas distintas en total (evaluadas = atenciones × columnas comparadas) y, solo de las columnas que
        difieren, las atenciones distintas de esa columna (evaluadas = atenciones comparadas).

      - La hora de alta: hora y minuto de `dim_horario` contra los del staging (evaluadas = atenciones comparadas).
      - Los atributos de las dimensiones: el total (evaluadas = atenciones × atributos) y, solo de los atributos que
        difieren, las atenciones distintas de ese atributo.

    Las atenciones que la carga apartó a cuarentena no están en la bodega y no se comparan.

    QR-EXA-02, por fuente, con el mismo staging: las atenciones del hecho = las atenciones del staging menos las filas
    que su tabla base tiene en cuarentena (la cuarentena aparta la atención completa; evaluadas = las esperadas, incumplen
    = la diferencia con las del hecho, en un sentido o en el otro).
    """
    hecho, definicion = hecho_de(contrato)
    columnas = _columnas_comparables(definicion)
    tipos = {c["name"]: c["type"] for c in inspect(conexion).get_columns(hecho, schema=esquema_de(contrato))}
    resultados = []
    for fuente, run_id in _carga_de(conexion, contrato).items():
        carpeta = staging_dirs.get(fuente)
        vigente = staging_vigente(carpeta, run_id)
        resultados.append(Resultado(REGLA, f"{fuente}: staging de la carga ({run_id})", 1, 0 if vigente else 1))
        if not vigente:
            continue

        horas = {n: d for n, d in definicion["columnas"].items() if d.get("resolucion") == "horario"}
        dimensiones = _dimensiones_del_hecho(contrato, definicion)
        # La primera toma de una tabla de varias filas se elige con todas las columnas que se toman de ella (medidas del
        # hecho y atributos de dimensiones), como en el Loader; por eso se calcula una sola vez con la unión
        crudo = _esperado(contrato, fuente, {**columnas, **horas, **_atributos_pedidos(dimensiones)}, carpeta)
        esperado = crudo[list(columnas)]
        obtenido = _obtenido(conexion, contrato, fuente, columnas)
        sin_staging = ~obtenido.index.isin(esperado.index)
        resultados.append(Resultado(REGLA, f"{fuente}: atenciones de la bodega que no están en el staging",
                                    len(obtenido), int(sin_staging.sum())))
        base = definicion["filas"][fuente]
        esperadas = crudo.index.nunique() - _atenciones_apartadas(conexion, contrato, fuente, base)
        resultados.append(Resultado(REGLA_ATENCIONES, f"{fuente}: atenciones del hecho = staging menos cuarentena ({base})",
                                    esperadas, abs(esperadas - len(obtenido))))
        comunes = obtenido.index[~sin_staging]
        esperado, obtenido = esperado.loc[comunes], obtenido.loc[comunes]

        por_columna = {nombre: int(_distintas(esperado[nombre], obtenido[nombre], tipos[nombre],
                                              d.get("resolucion") == "calendario").sum())
                       for nombre, d in columnas.items()}
        resultados.append(Resultado(REGLA, f"{fuente}: celdas de {hecho} contra el staging ({len(columnas)} columnas)",
                                    len(comunes) * len(columnas), sum(por_columna.values())))
        resultados += [Resultado(REGLA, f"{fuente}: {hecho}.{nombre} contra el staging", len(comunes), n)
                       for nombre, n in por_columna.items() if n]

        if horas:
            resultados += _verificar_horas(conexion, contrato, fuente, list(horas), crudo, comunes)
        resultados += _verificar_atributos(conexion, contrato, fuente, dimensiones, crudo, comunes)
    return resultados
