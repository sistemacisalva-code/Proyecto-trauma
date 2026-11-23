"""Instrumento puntuacion_de_severidad: regiones del ISS y puntaje ISS (reglas compartidas con el Excel)."""
import pandas as pd

from etl.transform.common.quality import ReporteCalidad
from etl.transform.common.severidad import (  # noqa: F401  (se reexportan para quien las importaba de aquí)
    ESPECIFICACION_SEVERIDAD,
    REGIONES_ISS,
    convertir_severidad,
)

NOMBRE = "puntuacion_de_severidad"
CATEGORICAS = ()


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    # Tipo, rango y regla del ISS: etl/transform/common/severidad.py
    convertir_severidad(df, reporte, NOMBRE)
    return df
