"""
Resolución del contrato sobre el staging, sin base de datos.

Reúne por atención lo que alimenta el hecho y sus dimensiones (con la primera toma de las tablas de varias filas),
arma las filas de cada bloque de puente antes de resolver sus claves y cuenta, por uso, qué filas se usan y por qué
no se usan las demás. La escritura en PostgreSQL está en `dimensiones.py` y en el Loader.

Las columnas de los marcos se llaman 'tabla.columna' (el origen del contrato), para que dos tablas con una columna
del mismo nombre no choquen.
"""
import pandas as pd

from etl.load.warehouse.contrato import CLAVE_ATENCION

SIN_DATO = "Sin dato"
NO_APLICA = "No aplica"
COLUMNA_SECUENCIA = "secuencia"


def origen(definicion: dict, fuente: str, campo: str = "origen") -> str | None:
    """'tabla.columna' de una columna del contrato en una fuente (`origen` o `mapeado`), o None si no la trae."""
    return (definicion.get(campo) or {}).get(fuente)


def _con_nombres_de_origen(df: pd.DataFrame, tabla: str, columnas: list[str]) -> pd.DataFrame:
    """La clave de la atención más una columna 'tabla.columna' por columna pedida (la clave también puede serlo)."""
    salida = df[[CLAVE_ATENCION]].copy()
    for columna in columnas:
        salida[f"{tabla}.{columna}"] = df[columna]
    return salida


def _por_tabla(origenes: set[str]) -> dict[str, list[str]]:
    """Agrupa los orígenes 'tabla.columna' por tabla de staging: {tabla: [columnas]}, ordenado para que el resultado
    no dependa del orden del conjunto. Dice qué columnas hay que traer de cada tabla."""
    agrupados: dict[str, list[str]] = {}
    for valor in sorted(origenes):
        tabla, columna = valor.split(".")
        agrupados.setdefault(tabla, []).append(columna)
    return agrupados


def exigir_grano_atencion(df: pd.DataFrame, tabla: str) -> None:
    """El grano declarado en el contrato se confirma al leer: una fila por atención."""
    repetidas = df[CLAVE_ATENCION].duplicated()
    if repetidas.any():
        raise ValueError(f"La tabla de staging '{tabla}' se declaró de grano atención y repite "
                         f"{int(repetidas.sum())} atenciones")


def primera_toma(df: pd.DataFrame, columnas: list[str], orden: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Por atención, la primera fila con algún valor en `columnas`, según `orden` (vacíos al final; en empate, el orden
    del staging). Esa misma fila alimenta todas las columnas: no se mezclan tomas.

    Returns:
        (una fila por atención con valores, {"cargadas", "otra_toma", "sin_valor"}).
    """
    con_valor = df[columnas].notna().any(axis=1)
    candidatas = df[con_valor]
    if orden:
        candidatas = candidatas.sort_values(orden, kind="stable", na_position="last")
    elegidas = candidatas.drop_duplicates(CLAVE_ATENCION, keep="first")
    return elegidas, {"cargadas": len(elegidas), "otra_toma": len(candidatas) - len(elegidas),
                      "sin_valor": int((~con_valor).sum())}


def marco_del_hecho(tablas: dict[str, pd.DataFrame], filas: str, origenes: set[str],
                    declaradas: dict[str, dict]) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    """
    Una fila por atención de la tabla `filas`, con una columna 'tabla.columna' por cada origen del hecho y de sus
    dimensiones. Las tablas de grano atención se unen por la atención; las de varias filas, por su primera toma.

    Returns:
        (marco, {tabla de staging: conteo del uso}).
    """
    por_tabla = _por_tabla(origenes)
    por_tabla.setdefault(filas, [])
    exigir_grano_atencion(tablas[filas], filas)
    marco = tablas[filas][[CLAVE_ATENCION]].copy()
    conteos = {}
    for tabla, columnas in por_tabla.items():
        df, declaracion = tablas[tabla], declaradas[tabla]
        if declaracion["grano"] == "atencion":
            exigir_grano_atencion(df, tabla)
            elegidas, conteos[tabla] = df, {"cargadas": len(df)}
        else:
            orden = declaracion.get("orden") or []
            valores = [c for c in df.columns if c != CLAVE_ATENCION and c not in orden]
            elegidas, conteos[tabla] = primera_toma(df, valores, orden)
        marco = marco.merge(_con_nombres_de_origen(elegidas, tabla, columnas), on=CLAVE_ATENCION, how="left")
    return marco, conteos


def combinaciones(marco: pd.DataFrame, atributos: dict[str, str | None], texto: set[str],
                  vacio: str = "sin_dato") -> pd.DataFrame:
    """
    Los atributos de una dimensión para cada fila del marco, con los miembros por defecto: un atributo de
    texto vacío es 'Sin dato'; si todos están vacíos, la fila es la combinación 'Sin dato' o, con `vacio: no_aplica`,
    la 'No aplica'. Los atributos que no son texto (p. ej. `quinquenio_orden`) quedan en NULL.

    Args:
        atributos: {columna de la dimensión: 'tabla.columna' del marco, o None si la fuente no la trae}.
        texto: columnas de la dimensión que son de texto en el DDL.
    """
    datos = pd.DataFrame(
        {columna: marco[o].astype(object).where(marco[o].notna(), None) if o
         else pd.Series(None, index=marco.index, dtype=object)
         for columna, o in atributos.items()},
        index=marco.index,
    )
    vacia = datos.isna().all(axis=1)
    for columna in atributos:
        if columna in texto:
            datos[columna] = datos[columna].where(datos[columna].notna(), SIN_DATO)
    if vacio == "no_aplica":
        for columna in atributos:
            datos.loc[vacia, columna] = NO_APLICA if columna in texto else None
    return datos


def filas_de_puente(tablas: dict[str, pd.DataFrame], bloque: dict, fuente: str, contrato_tablas: dict[str, dict]
                    ) -> tuple[pd.DataFrame, str, dict[str, dict[str, int]]] | None:
    """
    Filas de un bloque de puente en una fuente, antes de resolver sus claves: la tabla de `filas` unida por la
    atención a las tablas de grano atención que consulta (el mecanismo primario del Excel, copiado a cada lesión),
    sin las filas que no traen ningún valor propio, en el orden de la secuencia y con ella si el bloque la tiene.

    Returns:
        None si la fuente no tiene filas para el bloque; si no, (filas, tabla de filas, conteos por tabla). El conteo
        de la tabla de filas trae `sin_valor` (el Loader agrega `cargadas` y `duplicado`). Una tabla de consulta
        cuenta como cargadas las filas cuya atención tiene filas en el puente y como `sin_valor` las demás: no
        aportan valor a ninguna fila del puente.
    """
    tabla_filas = bloque["filas"][fuente]
    if tabla_filas is None:
        return None

    origenes = set()
    for definicion in bloque["columnas"].values():
        destino = contrato_tablas.get(definicion.get("dimension"), {})
        if definicion.get("resolucion") == "dimension" and destino.get("tipo") == "dimension":
            origenes |= {origen(d, fuente) for d in destino["columnas"].values()}
        origenes |= {origen(definicion, fuente), origen(definicion, fuente, "mapeado")}
    origenes.discard(None)
    banderas = {origen(d, fuente, "mapeado") for d in bloque["columnas"].values()} - {None}
    por_tabla = _por_tabla(origenes)

    orden = (bloque.get("orden") or {}).get(fuente) or []
    propias = por_tabla.get(tabla_filas, [])
    df = tablas[tabla_filas]
    # Las columnas de orden conservan su nombre; una misma columna puede ser orden y origen (fecha del procedimiento)
    filas = df[[CLAVE_ATENCION, *orden]].copy()
    for columna in propias:
        filas[f"{tabla_filas}.{columna}"] = df[columna]

    # Sin valor: ninguna columna propia trae dato (la bandera de mapeo no es un valor)
    valores = [f"{tabla_filas}.{c}" for c in propias if f"{tabla_filas}.{c}" not in banderas]
    con_valor = filas[valores].notna().any(axis=1)
    conteos = {tabla_filas: {"sin_valor": int((~con_valor).sum())}}
    filas = filas[con_valor]

    for tabla, columnas in por_tabla.items():
        if tabla == tabla_filas:
            continue
        consulta = tablas[tabla]
        exigir_grano_atencion(consulta, tabla)
        usadas = consulta[CLAVE_ATENCION].isin(filas[CLAVE_ATENCION])
        conteos[tabla] = {"cargadas": int(usadas.sum()), "sin_valor": int((~usadas).sum())}
        filas = filas.merge(_con_nombres_de_origen(consulta, tabla, columnas), on=CLAVE_ATENCION, how="left")

    if orden:
        filas = filas.sort_values([CLAVE_ATENCION, *orden], kind="stable", na_position="last")
    if any(d.get("resolucion") == "secuencia" for d in bloque["columnas"].values()):
        filas[COLUMNA_SECUENCIA] = filas.groupby(CLAVE_ATENCION, sort=False).cumcount() + 1
    return filas.reset_index(drop=True), tabla_filas, conteos


def texto_sin_mapeo(filas: pd.DataFrame, columna_fuente: dict, fuente: str) -> pd.Series:
    """
    El texto del staging de la columna `de` solo en las filas que no se mapearon (sin él, dos textos distintos sin
    código chocarían en la clave del puente); NULL si está mapeada o si
    la fuente no tiene bandera.
    """
    valor, bandera = origen(columna_fuente, fuente), origen(columna_fuente, fuente, "mapeado")
    if not valor or not bandera:
        return pd.Series(None, index=filas.index, dtype=object)
    no_mapeado = filas[valor].notna() & ~filas[bandera].fillna(False).astype(bool)
    return filas[valor].astype(object).where(no_mapeado, None)
