"""Instrumento motivo_de_consulta: solo se estandariza el texto libre de otras_sustancias_de_abuso,
con las mismas reglas que el Excel."""
import pandas as pd

from etl.transform.common.quality import ReporteCalidad
from etl.transform.common.sustancias import estandarizar_sustancias  # reglas compartidas con el Excel histórico

NOMBRE = "motivo_de_consulta"
CATEGORICAS = ()


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    # Mismas correcciones que el Excel (config/catalogos/sustancias_correcciones.yaml): solo ortografía, sin unificar
    # negaciones ni sinónimos; los valores que no son sustancias se invalidan y se cuentan. El resto del instrumento
    # pasa sin cambios.
    estandarizar_sustancias(df, reporte, NOMBRE, "otras_sustancias_de_abuso")
    return df
