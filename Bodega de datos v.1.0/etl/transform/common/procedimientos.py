"""Reglas de procedimientos compartidas por REDCap y el Excel histórico: fechas contra la estancia y duración."""
import pandas as pd

from etl.transform.common.quality import ReporteCalidad

COL_INICIO = "fecha_y_hora_de_procedimiento"
COL_FIN = "fecha_y_hora_de_fin_procedimiento"
COL_DURACION = "duracion_procedimiento_seg"
COL_LLEGADA = "fecha_y_hora_de_llegada_del_paciente"
COL_ALTA = "fecha_y_hora_de_alta"
LIMITE_DURACION_SEG = 86400  # 24 h, solo informativo: falta saber si hay procedimientos legítimos más largos

# Estancia = de la llegada del paciente al alta, ambos extremos incluidos y SIN margen de tolerancia: el personal médico
# indicó (2026-10-31) que ya no se admiten los 7 días a cada lado que se usaban antes.
# El margen sigue siendo un parámetro de las reglas por si se vuelve a necesitar; su valor por defecto es 0.
MARGEN_ESTANCIA_HORAS = 0


def resolver_fechas_procedimiento(proc: pd.DataFrame, ref: pd.DataFrame, reporte: ReporteCalidad, bloque: str,
                                  llave: str = "record_id",
                                  margen_horas: float = MARGEN_ESTANCIA_HORAS) -> None:
    """Invalida la fecha que cae fuera de la estancia cuando el fin es anterior al inicio.

    Si una de las dos queda fuera de la estancia (con el margen, que por defecto es 0) y la otra dentro, la de fuera es
    la errónea y se invalida (NA). Sin evidencia (ambas dentro, ambas fuera, o fuera por menos del margen) se conservan
    las dos y el caso queda para revisión manual. `ref` debe traer una fila por `llave` con la llegada
    y el alta. El índice de proc se conserva en el merge para que las máscaras se alineen por etiqueta.
    `llave` es el identificador del episodio en cada fuente (REDCap: record_id; Excel: traumaregisterrecordid).
    """
    chk = (proc[[llave, COL_INICIO, COL_FIN]].rename_axis("idx").reset_index()
           .merge(ref[[llave, COL_LLEGADA, COL_ALTA]], on=llave, how="left", validate="many_to_one")
           .set_index("idx"))
    inicio, fin = chk[COL_INICIO], chk[COL_FIN]
    llegada, alta = chk[COL_LLEGADA], chk[COL_ALTA]
    margen = pd.Timedelta(hours=margen_horas)

    def dentro(f): return (f >= llegada) & (f <= alta)
    def fuera(f): return (f < llegada - margen) | (f > alta + margen)

    inconsistentes = inicio.notna() & fin.notna() & (fin < inicio)
    invalida_fin = inconsistentes & dentro(inicio) & fuera(fin)
    invalida_inicio = inconsistentes & dentro(fin) & fuera(inicio)
    sin_evidencia = inconsistentes & ~invalida_fin & ~invalida_inicio

    # Se registra antes de modificar, para que los conteos reflejen el estado de partida
    llaves = chk[llave]
    reporte.reportar_regla(bloque, "fin anterior a inicio sin evidencia para corregir (revision manual)",
                           inconsistentes, sin_evidencia, llaves,
                           [COL_INICIO, COL_FIN, COL_LLEGADA, COL_ALTA])
    reporte.registrar_correccion(bloque, COL_FIN, "fin anterior a inicio y fuera de la estancia por mas del margen",
                                 int(invalida_fin.sum()), "invalidado (NA)", llaves, invalida_fin, [COL_FIN, COL_INICIO])
    reporte.registrar_correccion(bloque, COL_INICIO, "inicio posterior al fin y fuera de la estancia por mas del margen",
                                 int(invalida_inicio.sum()), "invalidado (NA)", llaves, invalida_inicio, [COL_INICIO, COL_FIN])

    proc.loc[invalida_fin, COL_FIN] = pd.NaT
    proc.loc[invalida_inicio, COL_INICIO] = pd.NaT


def reportar_duracion_cero(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Duración de 0 segundos: solo se reporta (inicio y fin iguales; suele ser un fin copiado del inicio)."""
    reporte.reportar_regla(bloque, f"{COL_DURACION} igual a 0 s (inicio y fin iguales)",
                           df[COL_DURACION].notna(), df[COL_DURACION] == 0, reporte.llaves(df),
                           [COL_INICIO, COL_FIN])


def reportar_duracion_extensa(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Duración superior a 24 h: solo se reporta (puede ser legítima o un error de fecha)."""
    reporte.reportar_regla(bloque, f"{COL_DURACION} superior a 24 h ({LIMITE_DURACION_SEG} s)",
                           df[COL_DURACION].notna(), df[COL_DURACION] > LIMITE_DURACION_SEG,
                           reporte.llaves(df), [COL_INICIO, COL_FIN])
