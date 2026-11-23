"""Reglas de líquidos compartidas por REDCap y el Excel histórico: volúmenes en litros con límite duro y blando."""
import pandas as pd

from etl.transform.common.cleaning import convertir_numerico
from etl.transform.common.quality import ReporteCalidad

# Propuesta por validar con el equipo clínico. Un valor extremo no es un valor imposible: una reanimación masiva
# es posible en un politraumatizado grave; un volumen en mL digitado en litros no. Criterio general:
#   - límite duro (imposible o error de unidad): se invalida a NA y se cuenta en fuera_de_rango
#   - límite blando (extremo pero posible): solo se reporta, el valor se conserva
# Los límites se fijan con criterio clínico o de la literatura, nunca con el máximo observado en los datos.
# Unidad: litros (confirmada por el usuario, 2026-10-15).
LIMITE_DURO_LITROS = {"cristaloides": 30.0, "coloides": 10.0, "sangre": 10.0}
LIMITE_BLANDO_LITROS = {"cristaloides": 12.67, "coloides": 1.5, "sangre": 3.0}
VOLUMEN_MINIMO_PLAUSIBLE_L = 0.05  # un positivo menor sugiere un error de unidad


def convertir_liquidos(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Convierte los tres volúmenes a Float64 con su límite duro y reporta los límites blandos."""
    for col, tope in LIMITE_DURO_LITROS.items():
        convertir_numerico(df, reporte, bloque, col, "Float64", rango=(0, tope))

    for col, limite in LIMITE_BLANDO_LITROS.items():
        reporte.reportar_regla(bloque, f"{col} superior a {limite} L (extremo, se conserva)",
                               df[col].notna(), df[col] > limite, reporte.llaves(df), [col])

    # Un volumen en mililitros (p. ej. 500) supera el límite duro y cae en fuera_de_rango; el caso
    # inverso (0.5 digitado como 0.0005) se reporta aquí
    for col in LIMITE_DURO_LITROS:
        reporte.reportar_regla(bloque, f"{col} entre 0 y {VOLUMEN_MINIMO_PLAUSIBLE_L} L (exclusivo de 0): "
                                       "posible error de unidad",
                               df[col].notna(), (df[col] > 0) & (df[col] < VOLUMEN_MINIMO_PLAUSIBLE_L), reporte.llaves(df),
                               [col])
