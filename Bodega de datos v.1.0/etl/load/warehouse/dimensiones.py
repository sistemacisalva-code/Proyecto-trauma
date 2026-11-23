"""
Escritura en la bodega y recuperación de claves sustitutas: las claves
nunca se insertan; las filas de dimensión se agregan con `ON CONFLICT DO NOTHING` sobre su clave natural (UNIQUE) y
la clave se recupera después, por valor (catálogos) o por combinación (dimensiones).
"""
import pandas as pd
from sqlalchemy import Column, MetaData, String, Table, Text, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection


def reflejar(conexion: Connection, esquema: str, nombre: str) -> Table:
    """La tabla tal como está en la base (columnas, tipos y clave primaria): el DDL es la fuente de verdad."""
    return Table(nombre, MetaData(), schema=esquema, autoload_with=conexion)


def clave_primaria(tabla: Table) -> str:
    """Nombre de la clave primaria sustituta de la tabla (una sola columna; falla si es compuesta o no tiene)."""
    (columna,) = tabla.primary_key.columns
    return columna.name


def columnas_de_texto(tabla: Table) -> set[str]:
    """Columnas de tipo texto de la tabla según el DDL: reciben 'Sin dato' cuando vienen vacías; las
    numéricas y de fecha quedan en NULL."""
    return {c.name for c in tabla.columns if isinstance(c.type, (Text, String))}


def _nativo(valor):
    """Valor que entiende psycopg2: None para los vacíos de pandas y tipos de Python en vez de los de numpy."""
    if valor is None or (not isinstance(valor, (list, tuple, dict)) and pd.isna(valor)):
        return None
    return valor.item() if hasattr(valor, "item") else valor


def registros(df: pd.DataFrame) -> list[dict]:
    """Las filas del DataFrame como lista de diccionarios {columna: valor} con valores nativos, que es lo que
    recibe `conexion.execute` para insertar varias filas en una sola sentencia."""
    return [{columna: _nativo(valor) for columna, valor in fila.items()} for fila in df.to_dict("records")]


def insertar(conexion: Connection, tabla: Table, df: pd.DataFrame, sin_conflicto: bool = False) -> None:
    """Inserta las filas del DataFrame (sus columnas deben existir en la tabla); con `sin_conflicto`, ignora las que
    ya existen por su clave natural."""
    if df.empty:
        return
    sentencia = insert(tabla).on_conflict_do_nothing() if sin_conflicto else insert(tabla)
    conexion.execute(sentencia, registros(df))


def actualizar(conexion: Connection, tabla: Table, df: pd.DataFrame, llave: str) -> None:
    """
    Actualiza en su lugar las filas del DataFrame, que se buscan por su llave natural `llave` (columna del DataFrame
    y de la tabla); el resto de sus columnas reemplaza el valor guardado y la clave primaria no se toca.

    Las filas se cargan en una tabla temporal (con los tipos de la tabla destino, sin sus restricciones) y una sola
    sentencia `UPDATE ... FROM` las aplica: el costo no crece con una sentencia por fila. La temporal se elimina al
    terminar, así que la función se puede llamar más de una vez en la misma transacción.
    """
    if df.empty:
        return
    columnas = [c for c in df.columns if c != llave]
    temporal = Table(f"_actualizar_{tabla.name}", MetaData(), *[Column(c, tabla.c[c].type) for c in df.columns],
                     prefixes=["TEMPORARY"])
    temporal.create(conexion)
    insertar(conexion, temporal, df)
    conexion.execute(update(tabla).where(tabla.c[llave] == temporal.c[llave])
                     .values({c: temporal.c[c] for c in columnas}))
    temporal.drop(conexion)     # si algo falla antes, el rollback de la transacción la elimina


def ids_de_catalogo(conexion: Connection, tabla: Table, columna: str, valores: pd.Series) -> pd.Series:
    """
    Clave de cada valor en un catálogo (`columna NOT NULL UNIQUE`); agrega los valores nuevos.

    Raises:
        ValueError: si algún valor queda sin clave (no debería ocurrir: indicaría un catálogo inconsistente).
    """
    unicos = sorted({_nativo(v) for v in valores.dropna()})
    insertar(conexion, tabla, pd.DataFrame({columna: unicos}), sin_conflicto=True)
    pk = clave_primaria(tabla)
    existentes = dict(
        (valor, clave) for clave, valor in
        conexion.execute(select(tabla.c[pk], tabla.c[columna]).where(tabla.c[columna].in_(unicos))).all()
    ) if unicos else {}
    ids = valores.map(lambda v: existentes.get(_nativo(v)))
    if ids[valores.notna()].isna().any():
        raise ValueError(f"Valores sin clave en {tabla.fullname}.{columna}")
    return ids


def _para_unir(df: pd.DataFrame, texto: set[str]) -> pd.DataFrame:
    """Mismos tipos a los dos lados de la unión: texto como objeto y números como flotantes (NaN igual a NaN)."""
    return pd.DataFrame({
        c: df[c].astype(object) if c in texto else pd.to_numeric(df[c], errors="coerce").astype(float)
        for c in df.columns
    }, index=df.index)


def ids_de_dimension(conexion: Connection, tabla: Table, combinaciones: pd.DataFrame) -> pd.Series:
    """
    Clave de cada combinación de atributos en una dimensión (`UNIQUE NULLS NOT DISTINCT`); agrega las nuevas.

    Raises:
        ValueError: si una combinación queda sin clave (p. ej. dos combinaciones que el UNIQUE considera iguales
            difieren en un atributo fuera de él).
    """
    columnas = list(combinaciones.columns)
    insertar(conexion, tabla, combinaciones.drop_duplicates(), sin_conflicto=True)
    pk = clave_primaria(tabla)
    existentes = pd.DataFrame(conexion.execute(select(tabla.c[pk], *[tabla.c[c] for c in columnas])).mappings().all(),
                              columns=[pk, *columnas])
    texto = columnas_de_texto(tabla)
    unidas = _para_unir(combinaciones, texto).merge(
        _para_unir(existentes[columnas], texto).assign(**{pk: existentes[pk].to_numpy()}), on=columnas, how="left"
    )
    if unidas[pk].isna().any():
        raise ValueError(f"Combinaciones sin clave en {tabla.fullname}")
    return pd.Series(unidas[pk].astype(int).to_numpy(), index=combinaciones.index)
