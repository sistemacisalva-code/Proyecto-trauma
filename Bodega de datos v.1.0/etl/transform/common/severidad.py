"""Reglas de severidad compartidas por REDCap y el Excel histórico: regiones del ISS (AIS) y puntaje ISS."""
import numpy as np
import pandas as pd

from etl.transform.common.cleaning import convertir_numerico
from etl.transform.common.quality import ReporteCalidad

# Las seis regiones son las del ISS; cada una lleva su AIS (0 = sin lesión, 5 = crítica). Todas son enteras
# por definición (un decimal detiene la ejecución). ISS 0-75 (máximo teórico: 5² + 5² + 5²).
# Si el registro admite AIS 6 (lesión no sobreviviente, ISS 75 por convención), ampliar a (0, 6).

REGIONES_ISS = ["cabeza", "cara", "torax", "abdomen", "extremidades", "externo"]
ESPECIFICACION_SEVERIDAD = {
    **{region: ("Int64", True, (0, 5)) for region in REGIONES_ISS},
    "iss": ("Int64", True, (0, 75)),
}


def convertir_severidad(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Convierte las seis regiones y el ISS con su rango (fuera de rango se invalida y se cuenta) y reporta la regla
    de consistencia: ISS = suma de los cuadrados de las 3 regiones más graves (solo filas con las siete columnas
    presentes; se reporta, no se modifica)."""
    for col, (tipo, entero, rango) in ESPECIFICACION_SEVERIDAD.items():
        convertir_numerico(df, reporte, bloque, col, tipo, entero, rango)

    completas = df[REGIONES_ISS + ["iss"]].notna().all(axis=1)
    regiones = df[REGIONES_ISS].to_numpy(dtype="float64", na_value=np.nan)
    tres_mayores = np.sort(regiones, axis=1)[:, -3:]
    iss_calculado = pd.Series((tres_mayores ** 2).sum(axis=1), index=df.index)
    reporte.reportar_regla(bloque, "iss != suma de cuadrados de las 3 regiones mas graves",
                           completas, df["iss"] != iss_calculado, reporte.llaves(df), [*REGIONES_ISS, "iss"])
