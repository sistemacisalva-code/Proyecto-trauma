"""Reglas cronológicas compartidas por REDCap y el Excel histórico (solo reporte, no modifican datos).

Estancia del episodio: desde la llegada del paciente (`fecha_y_hora_de_llegada_del_paciente`) hasta el alta
hospitalaria (`fecha_y_hora_de_alta`), ambos extremos incluidos y con un margen de MARGEN_ESTANCIA_HORAS a cada lado
(el mismo de la resolución de procedimientos, decisión 2.19), que desde el 2026-10-31 es 0: sin tolerancia. Si falta la llegada o el alta, el evento no es evaluable.
"""
import pandas as pd

from etl.transform.common.procedimientos import COL_ALTA, COL_LLEGADA, MARGEN_ESTANCIA_HORAS
from etl.transform.common.quality import ReporteCalidad

BLOQUE_REPORTE = "cronologia"


def reportar_eventos_fuera_de_estancia(tablas: dict[str, pd.DataFrame], eventos, llegada: pd.Series,
                                       alta: pd.Series, reporte: ReporteCalidad, llave: str = "record_id",
                                       margen_horas: float = MARGEN_ESTANCIA_HORAS) -> None:
    """Cuenta, por cada (tabla, columna) de `eventos`, las fechas anteriores a la llegada o posteriores al alta (con el
    margen). `llegada` y `alta` van indexadas por la llave del episodio (una por episodio)."""
    for nombre in (llegada, alta):
        if not nombre.index.is_unique:
            raise ValueError("La llegada y el alta deben tener una fila por episodio (llave repetida)")
    margen = pd.Timedelta(hours=margen_horas)
    for tabla, col in eventos:
        df = tablas[tabla]
        # map por llave: devuelve una Serie con el índice de la propia tabla (sin alinear por posición)
        inicio, fin, fecha = df[llave].map(llegada), df[llave].map(alta), df[col]
        reporte.reportar_regla(BLOQUE_REPORTE, f"{tabla}.{col} fuera de la estancia (margen {margen_horas:g} h)",
                               fecha.notna() & inicio.notna() & fin.notna(),
                               (fecha < inicio - margen) | (fecha > fin + margen), llaves=df[llave],
                               campos=[f"{tabla}.{col}", COL_LLEGADA, COL_ALTA])


def reportar_reglas_ventilador(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str,
                               col_inicio: str = "fecha_y_hora_de_inicio_del_ventilador",
                               col_termino: str = "fecha_y_hora_de_termino_del_ventilador") -> None:
    """Término anterior al inicio y ventilador con solo una de las dos fechas (fechas ya convertidas)."""
    inicio, termino = df[col_inicio], df[col_termino]
    llaves = reporte.llaves(df)
    reporte.reportar_regla(bloque, f"{col_termino} anterior al inicio", inicio.notna() & termino.notna(), termino < inicio,
                           llaves, [col_termino, col_inicio])
    reporte.reportar_regla(bloque, "ventilador con solo una de las dos fechas (inicio o termino)",
                           inicio.notna() | termino.notna(), inicio.notna() != termino.notna(), llaves,
                           [col_inicio, col_termino])
