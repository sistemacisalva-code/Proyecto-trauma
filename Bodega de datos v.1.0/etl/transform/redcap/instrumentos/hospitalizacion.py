"""Instrumento hospitalizacion."""
import pandas as pd

from etl.transform.common.cleaning import convertir_fecha, convertir_numerico
from etl.transform.common.quality import ReporteCalidad

NOMBRE = "hospitalizacion"
CATEGORICAS = ()


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    # El formato se declara por columna: la admisión no lleva hora y el alta SÍ trae segundos
    convertir_fecha(df, reporte, NOMBRE, "fecha_de_admision", "%Y-%m-%d")
    convertir_fecha(df, reporte, NOMBRE, "fecha_y_hora_de_alta", "%Y-%m-%d %H:%M:%S")

    # El alta no puede ser anterior a la admisión (se compara solo la fecha, porque la admisión no lleva
    # hora). Se reporta, no se modifica.
    reporte.reportar_regla(NOMBRE, "fecha_y_hora_de_alta anterior a fecha_de_admision",
                           df["fecha_de_admision"].notna() & df["fecha_y_hora_de_alta"].notna(),
                           df["fecha_y_hora_de_alta"].dt.normalize() < df["fecha_de_admision"], reporte.llaves(df),
                           ["fecha_de_admision", "fecha_y_hora_de_alta"])

    # dias_de_hospitalizacion es un campo derivado de las fechas. Los negativos coinciden con altas
    # anteriores a la admisión (no son un signo mal digitado): NO se aplica valor absoluto. Contrato:
    # una estancia no es negativa, sin tope superior; los negativos se invalidan y se cuentan.
    convertir_numerico(df, reporte, NOMBRE, "dias_de_hospitalizacion", "Int64",
                       entero=True, rango=(0, float("inf")))

    # Los días reportados deben coincidir con los calculados desde las fechas (se reporta, no se modifica)
    dias_calculados = (df["fecha_y_hora_de_alta"].dt.normalize() - df["fecha_de_admision"]).dt.days
    reporte.reportar_regla(NOMBRE, "dias_de_hospitalizacion distinto de los dias calculados desde las fechas",
                           df["dias_de_hospitalizacion"].notna() & dias_calculados.notna(),
                           df["dias_de_hospitalizacion"] != dias_calculados, reporte.llaves(df),
                           ["dias_de_hospitalizacion", "fecha_de_admision", "fecha_y_hora_de_alta"])
    return df
