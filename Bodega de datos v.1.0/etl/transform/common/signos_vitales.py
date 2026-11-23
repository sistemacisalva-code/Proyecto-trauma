"""Reglas de signos vitales compartidas por REDCap y el Excel histórico: tipos, rangos y consistencia."""
import pandas as pd

from etl.transform.common.cleaning import convertir_duracion, convertir_numerico
from etl.transform.common.quality import ReporteCalidad

# columna -> (tipo, entero, rango de plausibilidad fisiológica). Los rangos detectan errores de captura, no son
# rangos clínicos normales; el valor fuera de rango se invalida (NA) y se reporta. PROPUESTA: validar los límites
# Frecuencias, presiones y Glasgow son conteos enteros por definición (2026-10-19):
# un decimal detiene la ejecución para decidir cómo tratarlo.
ESPECIFICACION_NUMERICA = {
    "frecuencia_cardiaca":         ("Int64", True, (0, 300)),       # latidos/min
    "presion_arterial_sistolica":  ("Int64", True, (0, 300)),       # mmHg
    "presion_arterial_diastolica": ("Int64", True, (0, 200)),       # mmHg
    "frecuencia_respiratoria":     ("Int64", True, (0, 100)),       # respiraciones/min
    "saturacion_de_oxigeno":       ("Float64", False, (0, 100)),    # %
    "temperatura":                 ("Float64", False, (25, 45)),    # grados C (detecta valores en F)
    "peso":                        ("Float64", False, (0.5, 400)),  # kg
    "altura":                      ("Float64", False, (0.3, 2.5)),  # metros (unidad confirmada)
    "gcs_total":                   ("Int64", True, (3, 15)),
    "gcs_ocular":                  ("Int64", True, (1, 4)),
    "gcs_verbal":                  ("Int64", True, (1, 5)),
    "gcs_motora":                  ("Int64", True, (1, 6)),
}
# Enteros donde un decimal se invalida y se cuenta en vez de detener (decisión del usuario 2026-10-22: un decimal en
# REDCap; una frecuencia respiratoria fraccionaria no es medible y se trata como error de captura).
INVALIDAR_NO_ENTEROS = {"frecuencia_respiratoria"}
COMPONENTES_GCS = ["gcs_ocular", "gcs_verbal", "gcs_motora"]
COL_DURACION_PC = "duracion_de_la_perdida_de_conciencia"
LIMITE_PERDIDA_CONCIENCIA_MIN = 1440  # 24 h, propuesta por validar con el equipo clínico


def convertir_signos_vitales(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Tipa y valida las columnas de la especificación PRESENTES en df (el bloque 5 del Excel solo trae el Glasgow
    y la pérdida de conciencia); la duración HH:MM:SS pasa a minutos con tope de 24 h (sin decidir si pasa a segundos)."""
    for col, (tipo, entero, rango) in ESPECIFICACION_NUMERICA.items():
        if col in df.columns:
            convertir_numerico(df, reporte, bloque, col, tipo, entero, rango,
                               invalidar_no_enteros=col in INVALIDAR_NO_ENTEROS)
    if COL_DURACION_PC in df.columns:
        convertir_duracion(df, reporte, bloque, COL_DURACION_PC, rango_minutos=(0, LIMITE_PERDIDA_CONCIENCIA_MIN))


def reportar_reglas_signos_vitales(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Reglas de consistencia entre variables (solo se reportan, no modifican datos). Cada regla se evalúa solo si
    el bloque trae sus columnas. La altura no necesita regla propia: un valor en cm cae en fuera_de_rango."""
    if {"presion_arterial_sistolica", "presion_arterial_diastolica"} <= set(df.columns):
        reporte.reportar_regla(bloque, "presion diastolica > sistolica",
                               df["presion_arterial_sistolica"].notna() & df["presion_arterial_diastolica"].notna(),
                               df["presion_arterial_diastolica"] > df["presion_arterial_sistolica"], reporte.llaves(df),
                               ["presion_arterial_sistolica", "presion_arterial_diastolica"])
    if {"gcs_total", *COMPONENTES_GCS} <= set(df.columns):
        reporte.reportar_regla(bloque, "gcs_total != ocular + verbal + motora",
                               df[["gcs_total"] + COMPONENTES_GCS].notna().all(axis=1),
                               df["gcs_total"] != df[COMPONENTES_GCS].sum(axis=1), reporte.llaves(df),
                               ["gcs_total", *COMPONENTES_GCS])
