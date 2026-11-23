"""Instrumento procedimientos: fechas, resolución basada en evidencia y duración derivada."""
import pandas as pd

from etl.transform.common.cleaning import convertir_fecha, derivar_duracion_seg
from etl.transform.common.procedimientos import (  # reglas compartidas con el Excel histórico
    COL_DURACION, COL_FIN, COL_INICIO, LIMITE_DURACION_SEG, MARGEN_ESTANCIA_HORAS,
    reportar_duracion_cero, reportar_duracion_extensa,
)
from etl.transform.common.procedimientos import resolver_fechas_procedimiento as _resolver
from etl.transform.common.quality import ReporteCalidad

NOMBRE = "procedimientos"
CATEGORICAS = ()


def resolver_fechas_procedimiento(proc: pd.DataFrame, ref: pd.DataFrame, reporte: ReporteCalidad,
                                  margen_horas: float = MARGEN_ESTANCIA_HORAS) -> None:
    """Resolución basada en evidencia de REDCap (llave record_id); la regla vive en common/procedimientos.py."""
    _resolver(proc, ref, reporte, NOMBRE, "record_id", margen_horas)


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    convertir_fecha(df, reporte, NOMBRE, COL_INICIO, "%Y-%m-%d %H:%M")
    convertir_fecha(df, reporte, NOMBRE, COL_FIN, "%Y-%m-%d %H:%M")

    # La regla original sigue reportando el total de casos (antes de resolver)
    reporte.reportar_regla(NOMBRE, "fecha_y_hora_de_fin_procedimiento anterior a fecha_y_hora_de_procedimiento",
                           df[COL_INICIO].notna() & df[COL_FIN].notna(), df[COL_FIN] < df[COL_INICIO],
                           reporte.llaves(df), [COL_FIN, COL_INICIO])

    # Depende de los bloques ya transformados (ver DEPENDENCIAS): llegada (demográfica) y alta (hospitalización)
    referencia = (bloques["informacion_demografica"][["record_id", "fecha_y_hora_de_llegada_del_paciente"]]
                  .merge(bloques["hospitalizacion"][["record_id", "fecha_y_hora_de_alta"]],
                         on="record_id", how="outer", validate="one_to_one"))
    resolver_fechas_procedimiento(df, referencia, reporte)

    # Va DESPUÉS de la resolución: las fechas invalidadas dejan la duración en NA de forma natural
    derivar_duracion_seg(df, reporte, NOMBRE, COL_INICIO, COL_FIN, COL_DURACION)
    reportar_duracion_extensa(df, reporte, NOMBRE)
    reportar_duracion_cero(df, reporte, NOMBRE)
    return df
