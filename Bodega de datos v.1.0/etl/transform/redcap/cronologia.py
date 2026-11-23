"""Verificaciones cronológicas entre bloques (solo reporte, no modifican datos).

Se ejecutan después de transformar todos los instrumentos: necesitan fechas ya convertidas de varios
bloques. No invalidan nada porque una fecha fuera de lugar no dice cuál de las dos es la errónea; la
única corrección con evidencia (procedimientos) vive en su propio módulo (decisión 2.19).
"""
from itertools import combinations

import pandas as pd

from etl.transform.common.cronologia import BLOQUE_REPORTE, reportar_eventos_fuera_de_estancia
from etl.transform.common.quality import ReporteCalidad
from etl.transform.common.procedimientos import MARGEN_ESTANCIA_HORAS

# Fechas de grano episodio (una por record_id), en el orden cronológico esperado. Agregar el evento
# del trauma, cuando se confirme su columna, es una línea más.
CADENA_EPISODIO = (
    ("informacion_demografica", "fecha_y_hora_de_llegada_del_paciente"),
    ("hospitalizacion", "fecha_de_admision"),
    ("hospitalizacion", "fecha_y_hora_de_alta"),
)
COL_LLEGADA = CADENA_EPISODIO[0][1]
COL_ALTA = CADENA_EPISODIO[-1][1]

# Columnas sin hora: se comparan por día, no como las 00:00
SOLO_FECHA = frozenset({"fecha_de_admision"})

# Fechas de eventos (pueden repetirse dentro del episodio) que deben caer en la estancia
FECHAS_DE_EVENTO = (
    ("signos_vitales", "fecha_y_hora_de_signos_vitales"),
    ("laboratorio", "fecha_y_hora_de_laboratorio"),
    ("procedimientos", "fecha_y_hora_de_procedimiento"),
    ("procedimientos", "fecha_y_hora_de_fin_procedimiento"),
    ("uci", "fecha_y_hora_de_inicio_del_ventilador"),
    ("uci", "fecha_y_hora_de_termino_del_ventilador"),
)

# Límite inferior plausible de cualquier fecha (p. ej. inicio del registro). None = sin control hasta
# que el equipo lo defina.
FECHA_MINIMA_PLAUSIBLE: pd.Timestamp | None = None


def _tabla_episodio(bloques: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Una fila por record_id con las fechas de CADENA_EPISODIO (cada bloque debe ser de grano episodio)."""
    episodio = None
    for nombre in dict.fromkeys(b for b, _ in CADENA_EPISODIO):
        columnas = [c for b, c in CADENA_EPISODIO if b == nombre]
        parte = bloques[nombre][["record_id"] + columnas]
        episodio = parte if episodio is None else episodio.merge(
            parte, on="record_id", how="outer", validate="one_to_one")
    return episodio.set_index("record_id")


def _orden_entre_bloques(episodio: pd.DataFrame, reporte: ReporteCalidad) -> None:
    """Cada fecha de la cadena no puede ser posterior a una que le sigue en otro bloque.

    Los pares del mismo bloque (admisión y alta) ya tienen su regla en el instrumento hospitalizacion.
    """
    for (bloque_a, col_a), (bloque_b, col_b) in combinations(CADENA_EPISODIO, 2):
        if bloque_a == bloque_b:
            continue
        a, b = episodio[col_a], episodio[col_b]
        if col_a in SOLO_FECHA or col_b in SOLO_FECHA:
            a, b = a.dt.normalize(), b.dt.normalize()
        reporte.reportar_regla(BLOQUE_REPORTE, f"{col_a} posterior a {col_b}",
                               a.notna() & b.notna(), a > b, episodio.index.to_series(),
                               [f"{bloque_a}.{col_a}", f"{bloque_b}.{col_b}"])


def _eventos_en_la_estancia(bloques: dict[str, pd.DataFrame], episodio: pd.DataFrame,
                            reporte: ReporteCalidad, margen_horas: float) -> None:
    # Regla compartida con el Excel (common/cronologia.py): estancia = llegada del paciente -> alta, con margen
    reportar_eventos_fuera_de_estancia(bloques, FECHAS_DE_EVENTO, episodio[COL_LLEGADA], episodio[COL_ALTA],
                                       reporte, llave="record_id", margen_horas=margen_horas)


def _fechas_implausibles(bloques: dict[str, pd.DataFrame], reporte: ReporteCalidad,
                         fecha_referencia: pd.Timestamp | None) -> None:
    """Fechas posteriores a la extracción (imposibles) o anteriores al mínimo plausible."""
    for bloque, col in (*CADENA_EPISODIO, *FECHAS_DE_EVENTO):
        fecha = bloques[bloque][col]
        if fecha_referencia is not None:
            reporte.reportar_regla(BLOQUE_REPORTE, f"{bloque}.{col} posterior a la fecha de extraccion",
                                   fecha.notna(), fecha > fecha_referencia, reporte.llaves(bloques[bloque]),
                                   [f"{bloque}.{col}"])
        if FECHA_MINIMA_PLAUSIBLE is not None:
            reporte.reportar_regla(BLOQUE_REPORTE, f"{bloque}.{col} anterior a {FECHA_MINIMA_PLAUSIBLE:%Y-%m-%d}",
                                   fecha.notna(), fecha < FECHA_MINIMA_PLAUSIBLE, reporte.llaves(bloques[bloque]),
                                   [f"{bloque}.{col}"])


def verificar_cronologia(bloques: dict[str, pd.DataFrame], reporte: ReporteCalidad,
                         fecha_referencia: pd.Timestamp | None = None,
                         margen_horas: float = MARGEN_ESTANCIA_HORAS) -> None:
    """Registra en el reporte las reglas cronológicas entre bloques.

    Args:
        bloques: instrumentos ya transformados (fechas como datetime).
        fecha_referencia: momento de la extracción (partición más reciente). NO se usa la hora actual:
            la salida del transformer debe depender solo de la raw y del código (idempotencia).
        margen_horas: tolerancia para considerar una fecha de evento dentro de la estancia.
    """
    episodio = _tabla_episodio(bloques)
    _orden_entre_bloques(episodio, reporte)
    _eventos_en_la_estancia(bloques, episodio, reporte, margen_horas)
    _fechas_implausibles(bloques, reporte, fecha_referencia)
