"""Instrumento signos_vitales."""
import pandas as pd

from etl.transform.common.cleaning import convertir_fecha
from etl.transform.common.quality import ReporteCalidad
from etl.transform.common.signos_vitales import (  # reglas compartidas con el Excel histórico
    COMPONENTES_GCS, ESPECIFICACION_NUMERICA, LIMITE_PERDIDA_CONCIENCIA_MIN,
    convertir_signos_vitales, reportar_reglas_signos_vitales,
)

NOMBRE = "signos_vitales"
CATEGORICAS = ("calificador_de_la_frecuencia_respiratoria", "perdida_de_conciencia", "calificador_gcs", "avup")


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    convertir_fecha(df, reporte, NOMBRE, "fecha_y_hora_de_signos_vitales", "%Y-%m-%d %H:%M")
    # Tipos, rangos y duración de la pérdida de conciencia (texto HH:MM:SS -> minutos)
    convertir_signos_vitales(df, reporte, NOMBRE)
    reportar_reglas_signos_vitales(df, reporte, NOMBRE)
    return df
