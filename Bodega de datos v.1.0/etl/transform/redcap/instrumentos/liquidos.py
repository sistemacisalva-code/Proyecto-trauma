"""Instrumento liquidos: volúmenes en litros con límite duro (invalida) y límite blando (reporta)."""
import pandas as pd

from etl.transform.common.liquidos import (  # noqa: F401  (se reexportan para quien las importaba de aquí)
    LIMITE_BLANDO_LITROS,
    LIMITE_DURO_LITROS,
    VOLUMEN_MINIMO_PLAUSIBLE_L,
    convertir_liquidos,
)
from etl.transform.common.quality import ReporteCalidad

NOMBRE = "liquidos"
CATEGORICAS = ()


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    # Límites y reglas (decisión 2.20): etl/transform/common/liquidos.py, compartido con el Excel
    convertir_liquidos(df, reporte, NOMBRE)
    return df
