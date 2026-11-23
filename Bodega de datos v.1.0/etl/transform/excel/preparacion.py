"""Pasos del Excel histórico previos a la transformación por bloque (E0 a E8 del plan de transformación del Excel).

Lectura de la partición, nombres, vacíos, seudonimización, exclusión, fechas con ventana, edad y duplicados, más las
herramientas de estandarización que usan los bloques y las hojas. Todo cambio queda contado en el ReporteCalidad.
"""
import hashlib
import hmac
from pathlib import Path

import pandas as pd
import yaml

from etl.transform.common.cleaning import (
    convertir_numerico, eliminar_columnas, normalizar_nombre, registrar_estandarizacion, vacios_a_nulo,
    verificar_tasa_no_convertibles)
from etl.transform.common.demografia import EDAD_MAXIMA, derivar_quinquenios, edad_en_anios_cumplidos
from etl.transform.common.privacy import seudonimizar
from etl.transform.common.quality import ReporteCalidad

CLAVE = "traumaregisterrecordid"       # llave de registro_trauma y de las hojas hijas
HOJA_BASE = "registro_trauma"
VENTANA = (pd.Timestamp("2011-01-01"), pd.Timestamp("2022-12-31 23:59:59"))   # decisión 3.6
ANIOS_MARCADOR_VACIO = (1900,)          # posible "cero" de Excel; se invalida igual, pero se cuenta aparte
FORMATO_FECHA_HORA, FORMATO_FECHA = "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"
DOMINIO_HISTORIA = b"historia_clinica"  # separación de dominio: la historia no comparte seudónimo con el documento

# Columnas de registro_trauma que no usa ningún modelo (minimización, decisión 3.5). Nombres ya normalizados.
EXCLUIR_DEL_DW = [
    "policia_notificada", "codigo_postal", "pais", "inmunizacion_contra_el_tetanos",
    "fecha_de_nacimiento",    # se usa el quinquenio de la edad, no la fecha exacta
    "nombre", "apellido_paterno", "apellido_materno",
    "fecha_y_hora_de_notificacion_al_medico", "alerta_equipo_de_trauma", "nivel_de_alerta",
    # Prehospitalario: escena y transporte
    "agencia_de_transporte", "origen_del_transporte", "fecha_y_hora_de_notificacion_pre_hospitalaria",
    "fecha_y_hora_de_llegada_a_la_escena", "fecha_y_hora_de_salida_de_la_escena", "razon_de_la_demora",
    "reporte_of_formulario_pre_hospitalario_entregado", "tiempo_de_extricacion_hora",
    "tiempo_de_extricacion_minutos", "duracion_del_transporte_horas", "duracion_del_transporte_minutos",
    "procedimiento_realizado", "frecuencia_cardiaca_en_la_escena", "presion_arterial_sistolica_en_la_escena",
    "presion_arterial_diastolica_en_la_escena", "frecuencia_respiratoria_en_la_escena",
    "calificador_de_frecuencia_respiratoria_en_la_escena", "temperatura_en_la_escena_celsius",
    "saturacion_de_o2_en_la_escena", "frecuencia_cardiaca_durante_el_transporte",
    "presion_arterial_sistolica_de_transporte", "presion_diastolica_durante_el_transporte",
    "frecuencia_respiratoria_durante_el_transporte", "calificador_de_frecuencia_respiratoria_durante_el_transporte",
    "temperatura_durante_el_transporte_celsius", "saturacion_de_o2_durante_el_transporte",
    # Referencias y contra-referencia (nombres tal como salen de normalizar el original, con sus typos)
    "fecha_y_hora_de_envio_de_contra_referencia", "fecha_de_alta_de_contrar_referencia", "hospital_que_recibe",
    "otro_servicio", "recomendaciones", "numero_de_referencia_del_referencias_salientes",
    "fecha_de_envio_de_referencia", "fecha_de_referencia", "razon_de_la_referencia", "medico_que_refiere",
    "estado_de_referencia", "fecha_de_aceptada_del_referencia", "paciente_admitido", "servicio_que_recibe",
    "numero_de_referencia_del_ed", "numero_de_referencia_del_hospitalizacion",
]

COLUMNAS_FECHA_REGISTRO = {
    "fecha_y_hora_de_llegada_del_paciente": FORMATO_FECHA_HORA, "fecha_y_hora_de_llegada_del_medico": FORMATO_FECHA_HORA,
    "fecha_y_hora_del_evento": FORMATO_FECHA_HORA, "fecha_y_hora_de_la_disposicion": FORMATO_FECHA_HORA,
    "fecha_de_admision": FORMATO_FECHA, "fecha_y_hora_de_alta": FORMATO_FECHA_HORA,
}
COL_LLEGADA = "fecha_y_hora_de_llegada_del_paciente"


# --- E0 a E2: lectura, nombres y vacíos ------------------------------------------------------------------------
def leer_particion_reciente(raw_dir: str | Path) -> tuple[str, dict[str, pd.DataFrame]]:
    """Lee las hojas de la partición `load_date=...` más reciente (la carga histórica es única: no se consolidan
    particiones). Devuelve (nombre de la partición, {hoja: DataFrame})."""
    particiones = sorted(Path(raw_dir).glob("load_date=*"))
    if not particiones:
        raise FileNotFoundError(f"Sin particiones load_date=... en {raw_dir}")
    archivos = sorted(particiones[-1].glob("*.parquet"))
    if not archivos:
        raise FileNotFoundError(f"Sin archivos Parquet en {particiones[-1]}")
    return particiones[-1].name.removeprefix("load_date="), {a.stem: pd.read_parquet(a) for a in archivos}


def normalizar_columnas_excel(df: pd.DataFrame, hoja: str, renombres_hoja: dict) -> tuple[pd.DataFrame, dict]:
    """Renombra por nombre ORIGINAL (renombres_columnas_excel.yaml) y luego normaliza. Falla si el YAML nombra una
    columna inexistente o si la normalización colapsa dos columnas. Devuelve el df y la equivalencia original -> final."""
    ausentes = set(renombres_hoja) - set(df.columns)
    if ausentes:
        raise KeyError(f"{hoja}: renombres sobre columnas inexistentes: {sorted(ausentes)}")
    finales = [normalizar_nombre(renombres_hoja.get(c, c)) for c in df.columns]
    duplicados = {n for n in finales if finales.count(n) > 1}
    if duplicados:
        raise ValueError(f"{hoja}: la normalización colapsa columnas distintas: {sorted(duplicados)}")
    return df.set_axis(finales, axis=1), dict(zip(df.columns, finales))


def preparar_nombres_y_vacios(hojas: dict[str, pd.DataFrame], renombres_yaml: str | Path,
                              reporte: ReporteCalidad) -> dict[str, pd.DataFrame]:
    """E1 y E2 en todas las hojas: renombres semánticos + normalización y vacíos textuales a nulo real."""
    renombres = yaml.safe_load(Path(renombres_yaml).read_text(encoding="utf-8")) or {}
    desconocidas = set(renombres) - set(hojas)
    if desconocidas:
        raise KeyError(f"El YAML de renombres nombra hojas inexistentes: {sorted(desconocidas)}")
    salida = {}
    for hoja, df in hojas.items():
        df, equivalencia = normalizar_columnas_excel(df, hoja, renombres.get(hoja, {}))
        reporte.registrar_equivalencia(equivalencia, bloque=hoja)
        salida[hoja] = vacios_a_nulo(df)
    return salida


# --- E3 y E4: seudonimización y exclusión ---------------------------------------------------------------------
def seudonimizar_identidad(reg: pd.DataFrame, clave: str | bytes, reporte: ReporteCalidad) -> pd.DataFrame:
    """Documento e historia clínica -> seudónimos HMAC-SHA256 en la misma posición; los originales se eliminan.
    La historia usa una clave derivada para que un mismo número no produzca el mismo seudónimo que el documento;
    el seudónimo del documento sigue siendo comparable con REDCap (misma clave)."""
    clave_bytes = clave.encode() if isinstance(clave, str) else clave
    clave_historia = hmac.new(clave_bytes, DOMINIO_HISTORIA, hashlib.sha256).digest()
    for original, nueva, k in [("numero_de_identificacion", "documento_seudonimo", clave),
                               ("numero_de_historia_clinica", "historia_seudonimo", clave_historia)]:
        if original not in reg.columns:
            raise KeyError(f"{HOJA_BASE}: no existe la columna '{original}'")
        reg = reg.copy()
        reg.insert(reg.columns.get_loc(original), nueva, seudonimizar(reg[original], k))
        reg = reg.drop(columns=original)
        reporte.registrar_renombre(HOJA_BASE, original, nueva, "seudonimización HMAC-SHA256 (decisión 3.2)")
    return reg


IDENTIFICADORES_DIRECTOS = ["nombre", "apellido_paterno", "apellido_materno", "fecha_de_nacimiento"]


def excluir_columnas(reg: pd.DataFrame, columnas: list[str], reporte: ReporteCalidad) -> pd.DataFrame:
    """Quita las columnas sin uso en el modelo y deja cada una en `exclusiones` con su motivo. Falla si una no existe
    (cambio del origen)."""
    identificadores = [c for c in columnas if c in IDENTIFICADORES_DIRECTOS]
    resto = [c for c in columnas if c not in IDENTIFICADORES_DIRECTOS]
    reg = eliminar_columnas(reg, reporte, HOJA_BASE, identificadores,
                            "identificador directo o cuasi-identificador (igual que REDCap)")
    return eliminar_columnas(reg, reporte, HOJA_BASE, resto, "minimizacion: sin uso en ningun modelo")


# --- E5 y E6: fechas con ventana y reglas de cronología -------------------------------------------------------
def convertir_fecha_con_ventana(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str, formato: str,
                                max_no_convertibles: float = 0.5) -> None:
    """Convierte a datetime con formato explícito; invalida (NA) lo que cae fuera de VENTANA y lo cuenta por extremo.
    El año 1900 (posible "cero" de Excel) se invalida igual y se cuenta aparte como corrección."""
    original = df[col]
    fecha = pd.to_datetime(original, format=formato, errors="coerce")
    no_convertibles = int((original.notna() & fecha.isna()).sum())
    verificar_tasa_no_convertibles(bloque, col, no_convertibles, int(original.notna().sum()), max_no_convertibles)
    bajo, sobre = fecha.notna() & (fecha < VENTANA[0]), fecha.notna() & (fecha > VENTANA[1])
    marcador = int(fecha.dt.year.isin(ANIOS_MARCADOR_VACIO).sum())
    if marcador:
        reporte.registrar_correccion(bloque, col, f"anio {ANIOS_MARCADOR_VACIO} (posible marcador de vacio de Excel)",
                                     marcador, "invalidado a NA (cae bajo la ventana)")
    df[col] = fecha.mask(bajo | sobre)
    reporte.registrar_auditoria(bloque, col, original, df[col], no_convertibles,
                                int((bajo | sobre).sum()), int(bajo.sum()), int(sobre.sum()))


def regla_cronologica(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, nombre: str, a: str, b: str,
                      normalizar_b: bool = False, fecha_si_medianoche: bool = False) -> None:
    """Regla de coherencia a <= b (solo se reporta). `normalizar_b`: compara solo la fecha de b (admisión sin hora).
    `fecha_si_medianoche`: si b es exactamente 00:00:00 se compara solo la fecha (probable fecha sin hora)."""
    inicio = df[a]
    fin = df[b].dt.normalize() if normalizar_b else df[b]
    if fecha_si_medianoche:
        sin_hora = fin == fin.dt.normalize()
        inicio = inicio.where(~sin_hora, inicio.dt.normalize())
    reporte.reportar_regla(bloque, nombre, df[a].notna() & fin.notna(), inicio > fin, reporte.llaves(df), [a, b])


def fechas_y_cronologia_registro(reg: pd.DataFrame, reporte: ReporteCalidad) -> None:
    """Fechas de registro_trauma y sus reglas de cronología (solo se reportan)."""
    for col, formato in COLUMNAS_FECHA_REGISTRO.items():
        convertir_fecha_con_ventana(reg, reporte, HOJA_BASE, col, formato)
    regla_cronologica(reg, reporte, HOJA_BASE, "evento posterior a la llegada del paciente",
                      "fecha_y_hora_del_evento", COL_LLEGADA)
    regla_cronologica(reg, reporte, HOJA_BASE, "llegada del medico anterior a la llegada del paciente",
                      COL_LLEGADA, "fecha_y_hora_de_llegada_del_medico")
    regla_cronologica(reg, reporte, HOJA_BASE, "disposicion anterior a la llegada del paciente",
                      COL_LLEGADA, "fecha_y_hora_de_la_disposicion", fecha_si_medianoche=True)
    regla_cronologica(reg, reporte, HOJA_BASE, "alta anterior a la admision",
                      "fecha_de_admision", "fecha_y_hora_de_alta", normalizar_b=True)
    adelanto = reg[COL_LLEGADA] - reg["fecha_y_hora_de_llegada_del_medico"]
    for umbral, etiqueta in [(pd.Timedelta(hours=1), "mas de 1 h"), (pd.Timedelta(days=1), "mas de 24 h"),
                             (pd.Timedelta(days=7), "mas de 7 dias")]:
        reporte.reportar_regla(HOJA_BASE, f"llegada del medico anterior al paciente por {etiqueta}",
                               adelanto.notna(), adelanto > umbral, reporte.llaves(reg),
                               [COL_LLEGADA, "fecha_y_hora_de_llegada_del_medico"])


def edad_a_quinquenio(reg: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Edad registrada -> quinquenio (common/demografia.py, decisión 3.7); edad y unidad se eliminan al final."""
    convertir_numerico(reg, reporte, HOJA_BASE, "edad", "Int64", entero=True, rango=(0, EDAD_MAXIMA))
    reporte.reportar_regla(HOJA_BASE, "edad en meses >= 60 (equivale a 5 anios o mas)",
                           (reg["unidad_de_edad"] == "Meses") & reg["edad"].notna(), reg["edad"] >= 60,
                           reporte.llaves(reg), ["edad", "unidad_de_edad"])
    derivar_quinquenios(reg, reporte, HOJA_BASE, edad_en_anios_cumplidos(reg["edad"], reg["unidad_de_edad"]))
    return eliminar_columnas(reg, reporte, HOJA_BASE, ["edad", "unidad_de_edad"],
                             "cuasi-identificador: se conserva el quinquenio derivado")


# --- E8: duplicados (solo se marcan) --------------------------------------------------------------------------
def marcar_duplicados_registro(reg: pd.DataFrame, reporte: ReporteCalidad) -> None:
    """Cuatro niveles (decisión 3.3); nada se elimina. Requiere la fecha de llegada ya convertida."""
    reporte.marcar_duplicados(reg, HOJA_BASE, "fila_exacta", list(reg.columns), id_col=CLAVE, ignorar_nulos=False)
    reporte.marcar_duplicados(reg, HOJA_BASE, "clave_estructural", [CLAVE], id_col=CLAVE)
    reporte.marcar_duplicados(reg, HOJA_BASE, "regla_negocio_documento", ["documento_seudonimo", COL_LLEGADA],
                              id_col=CLAVE)
    reporte.marcar_duplicados(reg, HOJA_BASE, "regla_negocio_historia", ["historia_seudonimo", COL_LLEGADA],
                              id_col=CLAVE)


# --- Herramientas de estandarización para bloques y hojas -----------------------------------------------------
def estandarizar_etiquetas(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str, mapeo: dict,
                           regla: str = "etiqueta unificada con REDCap") -> int:
    """Reemplaza etiquetas según `mapeo` (lo que no está en el mapeo se conserva), audita la conservación y cuenta las
    filas que cambiaron. Devuelve ese conteo."""
    original = df[col].copy()
    df[col] = original.replace(mapeo)
    registrar_estandarizacion(reporte, bloque, col, original, df[col])
    cambiadas = int((original.notna() & original.astype("string").ne(df[col].astype("string")).fillna(False)).sum())
    reporte.registrar_correccion(bloque, col, regla, cambiadas, "estandarizado")
    return cambiadas


def mayusculas_sin_espacios(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str) -> None:
    """Texto libre a MAYÚSCULAS sin espacios sobrantes (procedimientos, sin mapear a CUPS), contado y auditado."""
    original = df[col].copy()
    df[col] = original.astype("string").str.strip().str.upper()
    registrar_estandarizacion(reporte, bloque, col, original, df[col])
    reporte.registrar_correccion(bloque, col, "texto a mayusculas sin espacios sobrantes (sin mapear a CUPS)",
                                 int((original.notna() & (original.astype("string") != df[col])).sum()), "estandarizado")
