"""Instrumento laboratorio: numéricas con rango, tipo de sangre, sangre en orina y toxicología.

Las reglas viven en etl/transform/common/laboratorio.py (compartidas con el Excel histórico); aquí solo se aplican en
el orden del instrumento. Las constantes se reexportan para quien las importaba de este módulo.
"""
import pandas as pd

from etl.transform.common.cleaning import (
    convertir_fecha,
    convertir_numerico,
    convertir_resultado_binario,
)
from etl.transform.common.laboratorio import (  # noqa: F401  (se reexportan)
    ESCALA_SANGRE_EN_ORINA,
    ESPECIFICACION_NUMERICA,
    GRUPOS_SANGUINEOS_VALIDOS,
    RANGOS_PLAUSIBLES,
    RESULTADOS_TOXICOLOGIA,
    convertir_otras_drogas,
    convertir_sangre_en_orina,
    convertir_tipo_sangre,
    normalizar_tipo_sangre,
    reportar_escala_orina,
    reportar_hematocrito_hemoglobina,
    reportar_otras_drogas_multiples,
    reportar_unidad_y_rangos_plausibles,
)
from etl.transform.common.quality import ReporteCalidad

NOMBRE = "laboratorio"
CATEGORICAS = tuple(RESULTADOS_TOXICOLOGIA) + ("tipo_de_sangre_y_factor_rh",)


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    convertir_fecha(df, reporte, NOMBRE, "fecha_y_hora_de_laboratorio", "%Y-%m-%d %H:%M")

    for col, (tipo, entero, rango) in ESPECIFICACION_NUMERICA.items():
        convertir_numerico(df, reporte, NOMBRE, col, tipo, entero, rango)

    convertir_tipo_sangre(df, reporte, NOMBRE)
    convertir_sangre_en_orina(df, reporte, NOMBRE)

    # Toxicología: dominio cerrado {NEGATIVO, POSITIVO} -> boolean. Una celda vacía no se imputa como
    # negativa. otras_drogas es nominal (dominio abierto): solo cambia el tipo a texto.
    for col in RESULTADOS_TOXICOLOGIA:
        convertir_resultado_binario(df, reporte, NOMBRE, col)
    convertir_otras_drogas(df, reporte, NOMBRE)

    _reglas_de_consistencia(df, reporte)
    return df


def _reglas_de_consistencia(lab: pd.DataFrame, reporte: ReporteCalidad) -> None:
    """Solo se reportan, no modifican datos."""
    reportar_otras_drogas_multiples(lab, reporte, NOMBRE)

    reportar_hematocrito_hemoglobina(lab, reporte, NOMBRE)

    reportar_escala_orina(lab, reporte, NOMBRE)
    reportar_unidad_y_rangos_plausibles(lab, reporte, NOMBRE)
