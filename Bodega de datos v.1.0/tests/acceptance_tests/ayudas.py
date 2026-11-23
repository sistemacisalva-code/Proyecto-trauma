"""
Ayudas de las pruebas de aceptación: lectura del staging sintético con pandas (el cálculo independiente) y consulta
de la bodega. Aquí no se usa el Loader ni el contrato de carga: solo el nombre de las tablas y columnas del staging.
"""
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from etl.load.warehouse.contrato import CLAVE_ATENCION
from etl.load.warehouse.staging import leer_tablas

ESQUEMA = "trauma_completo"
FUENTES = ("excel", "redcap")
SIN_DATO = "Sin dato"
NO_APLICA = "No aplica"
SIN_CODIGO = "SIN CODIGO CIE-10"
LLEGADA = "fecha_y_hora_de_llegada_del_paciente"
# Rango del calendario de la bodega (2011-01-01 a 2027-12-31). Una llegada fuera de él manda la atención a cuarentena
CALENDARIO = (pd.Timestamp("2011-01-01"), pd.Timestamp("2028-01-01"))


def ambas(tabla: str, columnas: dict[str, str]) -> dict[str, tuple[str, dict[str, str]]]:
    """La misma tabla y columnas del staging en las dos fuentes. `columnas` es {columna del staging: nombre}."""
    return {fuente: (tabla, columnas) for fuente in FUENTES}


def leer(staging_dirs: dict[str, str], origen: dict[str, tuple[str, dict[str, str]]]) -> pd.DataFrame:
    """
    Filas de una tabla del staging de cada fuente, juntas, con la clave de la atención y las columnas renombradas.
    `origen` es {fuente: (tabla, {columna del staging: nombre})}: las dos fuentes pueden usar tablas distintas.
    """
    partes = []
    for fuente, (tabla, columnas) in origen.items():
        df = leer_tablas(staging_dirs[fuente], {tabla: [CLAVE_ATENCION, *columnas]})[tabla]
        partes.append(df.rename(columns=columnas))
    return pd.concat(partes, ignore_index=True)


def atenciones(staging_dirs: dict[str, str], **extra: str) -> pd.DataFrame:
    """
    Las atenciones que deben estar en la bodega, con las columnas de `informacion_demografica` pedidas
    (`nombre="columna del staging"`). Se descarta la que llega fuera del calendario, que la carga aparta a cuarentena.
    """
    df = leer(staging_dirs, ambas("informacion_demografica", {LLEGADA: "llegada", **{c: n for n, c in extra.items()}}))
    dentro = df["llegada"].isna() | ((df["llegada"] >= CALENDARIO[0]) & (df["llegada"] < CALENDARIO[1]))
    return df[dentro].drop(columns="llegada").reset_index(drop=True)


def de_la_bodega(df: pd.DataFrame, universo: pd.DataFrame) -> pd.DataFrame:
    """Solo las filas de atenciones que están en la bodega (descarta la cuarentena y las filas sin atención)."""
    return df[df[CLAVE_ATENCION].isin(universo[CLAVE_ATENCION])]


def consulta(conexion: Connection, sql: str) -> pd.DataFrame:
    """Resultado de una consulta a la bodega como DataFrame."""
    resultado = conexion.execute(text(sql))
    return pd.DataFrame(resultado.all(), columns=list(resultado.keys()))


def iguales(esperado: pd.Series, obtenido: pd.Series) -> None:
    """Conteos idénticos por grupo (diferencia 0): mismos grupos y mismos valores, sin importar el orden."""
    pd.testing.assert_series_equal(
        esperado.sort_index().astype("int64"), obtenido.sort_index().astype("int64"), check_names=False)


def promedios_iguales(esperado: pd.DataFrame, obtenido: pd.DataFrame, llaves: list[str], tolerancia: float = 0.01) -> None:
    """
    Promedios por grupo con la misma tolerancia absoluta en todos (por defecto 0,01). Los grupos deben ser los mismos
    en ambos lados y un promedio vacío (NaN) solo coincide con otro vacío.
    """
    union = esperado.merge(obtenido, on=llaves, how="outer", suffixes=("_esperado", "_obtenido"), indicator=True)
    assert (union["_merge"] == "both").all(), f"Grupos distintos:\n{union[union['_merge'] != 'both'][llaves]}"
    for medida in [c for c in esperado.columns if c not in llaves]:
        assert np.isclose(union[f"{medida}_esperado"].astype(float), union[f"{medida}_obtenido"].astype(float),
                          rtol=0, atol=tolerancia, equal_nan=True).all(), f"{medida} difiere más de {tolerancia}"
