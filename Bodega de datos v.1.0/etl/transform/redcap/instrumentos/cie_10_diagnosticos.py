"""Instrumento cie_10_diagnosticos: solo se unifica la etiqueta CIE-10 de los códigos con dos redacciones.

Dos redacciones del mismo diagnóstico serían dos miembros de la dimensión y partirían los conteos."""
import pandas as pd

from etl.transform.common.cie10 import unificar_etiquetas_canonicas  # reglas compartidas con el Excel histórico
from etl.transform.common.quality import ReporteCalidad

NOMBRE = "cie_10_diagnosticos"
CATEGORICAS = ()
COLUMNAS_CIE10 = ("cie_10_diagnostico_definitivo",)   # antes codigo_cie_10_diagnostico_definitivo (YAML de renombres)


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    # El valor es la opción elegida en REDCap ("CÓDIGO ETIQUETA", con su * o † si lo tiene): se conserva y solo se
    # reasigna la redacción no canónica de B24, F03, I64, R31, T07 y V98. El resto del instrumento pasa sin cambios.
    unificar_etiquetas_canonicas(df, reporte, NOMBRE, COLUMNAS_CIE10)
    return df
