"""Reglas de mecanismo de lesión compartidas por REDCap y el Excel histórico: scq y altura_en_metros."""
import pandas as pd

from etl.transform.common.cleaning import convertir_numerico
from etl.transform.common.quality import ReporteCalidad

# Límite duro (invalida a NA y se cuenta). Solo lo que es verdad por definición: SCQ es un porcentaje de superficie
# corporal quemada (0 a 100) y la altura de una caída no es negativa. La altura no lleva tope superior (decisión del
# usuario, 2026-10-20). Decimales: SCQ admite medios puntos (regla de los nueves, p. ej. 4,5 %).
ESPECIFICACION_NUMERICA = {
    "scq": ("Float64", (0, 100)),
    "altura_en_metros": ("Float64", (0, float("inf"))),
}


def convertir_mecanismo(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Convierte scq y altura_en_metros con su rango; solo las columnas presentes en el bloque."""
    for col, (tipo, rango) in ESPECIFICACION_NUMERICA.items():
        if col in df.columns:
            convertir_numerico(df, reporte, bloque, col, tipo, rango=rango)
