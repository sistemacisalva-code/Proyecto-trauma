"""Instrumento uci: fechas del ventilador y dias_usados_uci (antes dias_usados)."""
import pandas as pd

from etl.transform.common.cleaning import convertir_fecha, convertir_numerico, renombrar_columnas
from etl.transform.common.cronologia import reportar_reglas_ventilador
from etl.transform.common.quality import ReporteCalidad

NOMBRE = "uci"
CATEGORICAS = ()

COL_INICIO = "fecha_y_hora_de_inicio_del_ventilador"
COL_TERMINO = "fecha_y_hora_de_termino_del_ventilador"
SEGUNDOS_POR_DIA = 86400
COL_DIAS = "dias_usados_uci"   # nombre común con registro_trauma del Excel (antes dias_usados)


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    # El export trae minutos, sin segundos
    convertir_fecha(df, reporte, NOMBRE, COL_INICIO, "%Y-%m-%d %H:%M")
    convertir_fecha(df, reporte, NOMBRE, COL_TERMINO, "%Y-%m-%d %H:%M")

    # dias_usados -> dias_usados_uci (nombre común con registro_trauma del Excel). Entero por contrato; se deja como
    # viene del origen (solo conversión de tipo, mínimo 0, sin tope superior); su calidad queda pendiente (31)
    df = renombrar_columnas(df, reporte, NOMBRE, {"dias_usados": COL_DIAS},
                            "nombre común con registro_trauma del Excel")
    convertir_numerico(df, reporte, NOMBRE, COL_DIAS, "Int64", entero=True, rango=(0, float("inf")))

    # Término anterior al inicio y ventilador con una sola fecha: reglas compartidas con el Excel (hoja 14)
    reportar_reglas_ventilador(df, reporte, NOMBRE, COL_INICIO, COL_TERMINO)
    inicio, termino = df[COL_INICIO], df[COL_TERMINO]

    # Definición provisional (4 filas evaluables en el diagnóstico): días completos (horas // 24)
    dias_calculados = (termino - inicio).dt.total_seconds() // SEGUNDOS_POR_DIA
    reporte.reportar_regla(NOMBRE, f"{COL_DIAS} distinto de los dias completos calculados (horas // 24)",
                           df[COL_DIAS].notna() & dias_calculados.notna(),
                           (df[COL_DIAS] != dias_calculados).fillna(False), reporte.llaves(df),
                           [COL_DIAS, COL_INICIO, COL_TERMINO])
    return df
