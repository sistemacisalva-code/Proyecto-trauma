"""Instrumento mecanismo_de_lesion."""
import pandas as pd

from etl.transform.common.cie10 import unificar_etiquetas_canonicas
from etl.transform.common.mecanismo import convertir_mecanismo  # reglas compartidas con el Excel histórico
from etl.transform.common.quality import ReporteCalidad

NOMBRE = "mecanismo_de_lesion"
CATEGORICAS = ()
COLUMNAS_CIE10 = ("cie10_mecanismos_de_lesiones_de_transito",           # nombres tras renombres_columnas_redcap.yaml
                  "cie_10_otros_mecanismos_de_lesion_excluye_transito")


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    # scq 0 a 100 y altura_en_metros >= 0 sin tope (límite duro: fuera de rango se invalida y se cuenta)
    convertir_mecanismo(df, reporte, NOMBRE)
    # Códigos CIE-10 del mecanismo: solo se unifica la etiqueta de los 6 códigos que REDCap ofrece con dos redacciones
    unificar_etiquetas_canonicas(df, reporte, NOMBRE, COLUMNAS_CIE10)
    return df
