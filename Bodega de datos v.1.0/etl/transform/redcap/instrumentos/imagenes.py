"""Instrumento imagenes."""
import pandas as pd

from etl.transform.common.cleaning import renombrar_columnas
from etl.transform.common.quality import ReporteCalidad

NOMBRE = "imagenes"
CATEGORICAS = ()


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    return renombrar_columnas(df, reporte, NOMBRE, {"descripcion": "descripcion_imagen"},
                              "claridad: alinear con DIM_IMAGEN del modelo")
