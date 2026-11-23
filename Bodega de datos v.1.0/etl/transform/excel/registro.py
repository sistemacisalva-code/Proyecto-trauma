"""registro_trauma del Excel histórico: división en bloques (config/mapeo_columnas_excel.yaml) y transformación de cada
bloque (E9). Cada función recibe el bloque con la llave y devuelve el bloque transformado; todo cambio queda contado."""
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from etl.transform.common.cleaning import (
    convertir_numerico, eliminar_columnas, normalizar_nombre, registrar_estandarizacion, renombrar_columnas)
from etl.transform.common.geografia import (
    clasificar_departamentos, clasificar_municipios, completar_departamento, departamento_por_municipio)
from etl.transform.common.liquidos import convertir_liquidos
from etl.transform.common.lugar_del_evento import mapear_lugar_del_evento
from etl.transform.common.mecanismo import convertir_mecanismo
from etl.transform.common.quality import ReporteCalidad
from etl.transform.common.severidad import convertir_severidad
from etl.transform.common.sustancias import estandarizar_sustancias
from etl.transform.excel.preparacion import CLAVE, estandarizar_etiquetas

ALINEAR = "alinear con el nombre de REDCap"
SIN_LIMITE = (0, float("inf"))

# Destinos de REDCap (hospitalizacion.disposicion_o_destino_del_paciente), copiados tal cual
DESTINOS_REDCAP = [
    "Domicilio",
    "Referido a otro hospital (se sugirió ir a otro hospital para tratamientos adicionales)",
    "Fallece  (Morgue)",                                    # REDCap trae dos espacios; se respeta
    "Sale contra el consejo médico", "Desconocido", "Otros", "Murió en el Departamento de emergencias",
    "Consulta externa",
    "Transferido a otro hospital (se transfirió vía ambulancia para tratamientos adicionales)",
    "Murió antes de la llegada",
]
DESTINO_ESTANDAR = {normalizar_nombre(d): d for d in DESTINOS_REDCAP}
DESTINO_ESTANDAR.update({"referido_a_otro_hospital": DESTINOS_REDCAP[1],
                         "transferido_a_otro_hospital": DESTINOS_REDCAP[8],
                         "murio_en_el_departamento_de_emergencia": DESTINOS_REDCAP[6]})
DESTINO_URGENCIAS = {
    "Fallece (Morgue)": "Fallece  (Morgue)", "Salida Contra Consejo Médico": "Sale contra el consejo médico",
    "Otro": "Otros", "No especificado": "Desconocido", "Murió antes de la llegada a hospital": "Murió antes de la llegada",
    "Referido a otro hospital": DESTINOS_REDCAP[1],
}   # "Internado...", "Admitido a la UCI" y "Sala de Operaciones" no tienen equivalente: se conservan
CONSOLIDADA = "consolidada en la columna estandarizada (auditada con registrar_estandarizacion)"
VACIA = "columna vacia o sin informacion suficiente"
SIN_DDL = "sin uso en ningun modelo (no esta en el DDL mini ni completo)"
MAPEO_DONACION = {"No especificado": "Sin especificar", "No disponible": "Sin especificar", "Si": "Sí"}
# Etiquetas que el Excel escribe distinto de REDCap para el mismo valor. Salieron de comparar los valores de las dos
# fuentes atributo por atributo (diccionario de QR-DOM-04, revisado por el usuario el 2026-10-31). El Excel adopta la
# etiqueta de REDCap: sin esto, la misma categoría entra dos veces en la dimensión y la bodega no se puede agrupar.
MAPEO_CAIDA = {"No": "NO", "Si": "SI", "No especificado": "NO ESPECIFICADO"}     # REDCap las trae en mayúsculas
MAPEO_VEHICULO = {"Camión o trailer": "Camión o tráiler",                        # falta la tilde en el Excel
                  "Vehículos todo terreno (Cuadrón)": "Vehículos todo terreno"}  # REDCap no trae el paréntesis
MAPEO_ESTADO_CIVIL = {"Viudo": "Viudo/a", "Union Libre": "Unión libre"}
MAPEO_PACIENTE_ASEGURADO = {"Si": "Sí"}
MAPEO_MUERTE_PREVENIBLE = {"Si": "Sí"}
VELOCIDAD_ESTANDAR = {"noespecificado": "No especificado", "bajavelocidad(<64km)": "Baja velocidad (< 64 KM)",
                      "altavelocidad(>64km)": "Alta velocidad(> 64 KM)"}   # el Excel adopta las de REDCap
COLUMNAS_DE_HOJA_SIGNOS_VITALES = ["perdida_de_conciencia", "duracion_de_la_perdida_de_conciencia",
                                   "gcs_ocular", "gcs_verbal", "gcs_motora", "gcs_total"]   # se toman de la hoja signos_vitales


# --- División ---------------------------------------------------------------------------------------------------
def leer_mapeo(ruta: str | Path) -> dict[str, list[str]]:
    return yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))["registro_trauma"]


def dividir_registro(reg: pd.DataFrame, mapeo: dict[str, list[str]]) -> dict[str, pd.DataFrame]:
    """Un bloque por entrada del mapeo, cada uno con la llave. Falla si una columna falta, sobra o se repite."""
    asignadas = [c for columnas in mapeo.values() for c in columnas]
    repetidas = sorted({c for c in asignadas if asignadas.count(c) > 1})
    inexistentes = sorted(set(asignadas) - set(reg.columns))
    sin_asignar = sorted(set(reg.columns) - set(asignadas) - {CLAVE})
    if repetidas or inexistentes or sin_asignar:
        raise ValueError(f"Mapeo de registro_trauma inconsistente: repetidas={repetidas}, "
                         f"inexistentes={inexistentes}, sin_asignar={sin_asignar}")
    return {bloque: reg[[CLAVE] + columnas].copy() for bloque, columnas in mapeo.items()}


# --- Bloques ----------------------------------------------------------------------------------------------------
def informacion_demografica(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Municipio (ciudad manda, canton_municipio rellena) y departamento estandarizados con el catálogo; departamento
    completado desde el municipio de confianza alta. El municipio estandarizado se llama `ciudad` (2026-10-22)."""
    b = "informacion_demografica"
    bl = eliminar_columnas(bl, reporte, b, ["otro_grupo_etnico"], VACIA)
    estandarizar_etiquetas(bl, reporte, b, "estado_civil", MAPEO_ESTADO_CIVIL)
    estandarizar_etiquetas(bl, reporte, b, "paciente_asegurado", MAPEO_PACIENTE_ASEGURADO)
    municipio_crudo = bl["ciudad"].fillna(bl["canton_municipio"])
    clasif = clasificar_municipios(municipio_crudo)
    bl["municipio"] = clasif["municipio"]
    registrar_estandarizacion(reporte, b, "municipio", municipio_crudo, bl["municipio"])
    bl = eliminar_columnas(bl, reporte, b, ["ciudad", "canton_municipio"], CONSOLIDADA)
    bl = renombrar_columnas(bl, reporte, b, {"provincia_estado": "departamento"}, "nombre del dominio geografico")
    crudo = bl["departamento"]
    bl["departamento"] = clasificar_departamentos(crudo)["departamento"]
    registrar_estandarizacion(reporte, b, "departamento", crudo, bl["departamento"])
    bl["departamento"], completado = completar_departamento(bl["municipio"], bl["departamento"], clasif["confianza"])
    reporte.registrar_correccion(b, "departamento", "departamento vacio completado desde el municipio (confianza alta)",
                                 int(completado.sum()), "completado")
    esperado = bl["municipio"].map(departamento_por_municipio())
    reporte.reportar_regla(b, "municipio y departamento discrepantes con el catalogo (solo se reporta)",
                           esperado.notna() & bl["departamento"].notna(), esperado != bl["departamento"],
                           reporte.llaves(bl), ["ciudad", "departamento"])
    return renombrar_columnas(bl, reporte, b, {"municipio": "ciudad"},
                              "nombre definido por el usuario para el municipio estandarizado")


def motivo_de_consulta(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Municipio y departamento del evento estandarizados; sustancias con las reglas de REDCap."""
    b = "motivo_de_consulta"
    bl = eliminar_columnas(bl, reporte, b, ["codigo_postal_de_lesiones", "valor_de_alcoholemia", "unidad_de_alcohol"],
                           VACIA)
    municipio_crudo = bl["ciudad_de_evento_de_la_lesion"].fillna(bl["condado_de_lesiones"])
    clasif = clasificar_municipios(municipio_crudo)
    bl["municipio_evento_de_la_lesion"] = clasif["municipio"]
    registrar_estandarizacion(reporte, b, "municipio_evento_de_la_lesion", municipio_crudo,
                              bl["municipio_evento_de_la_lesion"])
    depto = clasificar_departamentos(bl["estado_provincia_de_lesiones"])["departamento"]
    registrar_estandarizacion(reporte, b, "departamento_de_lesiones", bl["estado_provincia_de_lesiones"], depto)
    bl["departamento_de_lesiones"], completado = completar_departamento(
        bl["municipio_evento_de_la_lesion"], depto, clasif["confianza"])
    reporte.registrar_correccion(b, "departamento_de_lesiones",
                                 "departamento vacio completado desde el municipio (confianza alta)",
                                 int(completado.sum()), "completado")
    bl = eliminar_columnas(bl, reporte, b, ["ciudad_de_evento_de_la_lesion", "condado_de_lesiones",
                                            "estado_provincia_de_lesiones"], CONSOLIDADA)
    bl = eliminar_columnas(bl, reporte, b, ["pais_de_lesiones"], SIN_DDL)
    bl = renombrar_columnas(bl, reporte, b, {"otra_sustancia_de_abuso": "otras_sustancias_de_abuso"}, ALINEAR)
    estandarizar_sustancias(bl, reporte, b, "otras_sustancias_de_abuso")
    return bl


def mecanismo_de_lesion(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Nombres de REDCap, etiquetas de velocidad de REDCap y scq / altura con las reglas comunes."""
    b = "mecanismo_de_lesion"
    bl = renombrar_columnas(bl, reporte, b, {"accidente_de_trafico": "mecanismo_de_lesion_de_transito",
                                             "caida": "lesiones_de_caidas"}, ALINEAR)
    estandarizar_etiquetas(bl, reporte, b, "lesiones_de_caidas", MAPEO_CAIDA)
    estandarizar_etiquetas(bl, reporte, b, "tipo_de_vehiculo", MAPEO_VEHICULO)
    original = bl["velocidad_de_colision"]
    clave = original.astype("string").str.lower().str.replace(r"\s+", "", regex=True)
    bl["velocidad_de_colision"] = clave.map(VELOCIDAD_ESTANDAR).fillna(original)
    registrar_estandarizacion(reporte, b, "velocidad_de_colision", original, bl["velocidad_de_colision"])
    reporte.registrar_correccion(b, "velocidad_de_colision", "etiqueta unificada con REDCap",
                                 int((clave.isin(VELOCIDAD_ESTANDAR)
                                      & (original != bl["velocidad_de_colision"]).fillna(False)).sum()), "estandarizado")
    convertir_mecanismo(bl, reporte, b)
    return bl


def examen_fisico(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Sin cambios: la descripción es texto libre y mecanismo_primario ya viene como en REDCap."""
    return bl


def signos_vitales(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Sus columnas se toman de la hoja signos_vitales, la del instrumento de REDCap (las dos hojas no coinciden y no
    hay criterio para elegir por fila): aquí se eliminan y el bloque queda vacío."""
    return eliminar_columnas(bl, reporte, "signos_vitales", COLUMNAS_DE_HOJA_SIGNOS_VITALES,
                             "se toma de la hoja signos_vitales")


def puntuacion_de_severidad(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Regiones e ISS con las reglas comunes; kts y rts decimales; triss vacías se verifican y se eliminan."""
    b = "puntuacion_de_severidad"
    convertir_severidad(bl, reporte, b)
    for col in ["kts", "rts"]:
        convertir_numerico(bl, reporte, b, col, "Float64")
    triss = ["triss_contuso", "triss_penetrante"]
    con_datos = [c for c in triss if bl[c].notna().any()]
    if con_datos:
        raise ValueError(f"{b}: columnas triss que ya no estan vacias: {con_datos}")
    return eliminar_columnas(bl, reporte, b, triss, VACIA)


def hospitalizacion(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Días enteros >= 0 (decimal positivo truncado, negativo al entero inferior; contado), regla contra las fechas,
    destino al dominio de REDCap (lo que solo existe en el Excel se conserva hasta decidir su categoría) y etiquetas
    de donación y autopsia."""
    b = "hospitalizacion"
    dias = pd.to_numeric(bl["dias_de_hospitalizacion"], errors="coerce")
    decimales = dias.notna() & (dias % 1 != 0)
    ajustado = pd.Series(np.where(dias > 0, np.trunc(dias), np.floor(dias)), index=bl.index)
    bl["dias_de_hospitalizacion"] = bl["dias_de_hospitalizacion"].where(~decimales, ajustado)
    reporte.registrar_correccion(b, "dias_de_hospitalizacion",
                                 "decimal pasado a entero (positivo truncado a dias completos; negativo al entero inferior)",
                                 int(decimales.sum()), "truncado")
    convertir_numerico(bl, reporte, b, "dias_de_hospitalizacion", "Int64", entero=True, rango=SIN_LIMITE)
    calculados = (bl["fecha_y_hora_de_alta"].dt.normalize() - bl["fecha_de_admision"]).dt.days
    reporte.reportar_regla(b, "dias_de_hospitalizacion distinto de los dias calculados desde las fechas",
                           bl["dias_de_hospitalizacion"].notna() & calculados.notna(),
                           bl["dias_de_hospitalizacion"] != calculados, reporte.llaves(bl),
                           ["dias_de_hospitalizacion", "fecha_de_admision", "fecha_y_hora_de_alta"])
    col = "disposicion_o_destino_del_paciente_hospitalizacion"
    original = bl[col]
    clave = original.map(lambda v: normalizar_nombre(v) if pd.notna(v) else pd.NA)
    bl[col] = clave.map(DESTINO_ESTANDAR).fillna(original)
    registrar_estandarizacion(reporte, b, col, original, bl[col])
    reporte.registrar_correccion(b, col, "etiqueta unificada con REDCap",
                                 int((clave.isin(DESTINO_ESTANDAR) & (original != bl[col]).fillna(False)).sum()),
                                 "estandarizado")
    # muerte_prevenible_hospitalizacion no se estandariza: la dimensión toma la columna del bloque de urgencias y esta
    # no la usa ningún modelo del trabajo de grado (solo el DDL mini, fuera de alcance)
    for c in ["donacion_de_organos_hospitalizacion", "autopsia_hospitalizacion"]:
        estandarizar_etiquetas(bl, reporte, b, c, MAPEO_DONACION)
    return bl


def uci(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """uci_dias -> dias_usados_uci, entero >= 0 (mismo contrato que REDCap)."""
    bl = renombrar_columnas(bl, reporte, "uci", {"uci_dias": "dias_usados_uci"}, "alinear con el nombre dias_usados_uci")
    convertir_numerico(bl, reporte, "uci", "dias_usados_uci", "Int64", entero=True, rango=SIN_LIMITE)
    return bl


def liquidos(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Nombres de REDCap (la unidad, litros, queda en docs 3.10) y límites duro y blando de REDCap."""
    bl = renombrar_columnas(bl, reporte, "liquidos",
                            {"sangre_l": "sangre", "coloides_l": "coloides", "cristaloides_l": "cristaloides"},
                            "alinear con el nombre de REDCap; la unidad (litros) se documenta en docs")
    convertir_liquidos(bl, reporte, "liquidos")
    return bl


def atencion_urgencias(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Tiempos en sala enteros >= 0, destino y etiquetas de donación y autopsia al dominio de REDCap."""
    b = "atencion_urgencias"
    for col in ["tiempo_en_sala_de_emergencias_hora", "tiempo_en_sala_de_emergencias_minutos"]:
        convertir_numerico(bl, reporte, b, col, "Int64", entero=True, rango=SIN_LIMITE)
    reporte.reportar_regla(b, "tiempo_en_sala_de_emergencias_minutos mayor que 59 (se conserva)",
                           bl["tiempo_en_sala_de_emergencias_minutos"].notna(),
                           bl["tiempo_en_sala_de_emergencias_minutos"] > 59, reporte.llaves(bl),
                           ["tiempo_en_sala_de_emergencias_minutos"])
    estandarizar_etiquetas(bl, reporte, b, "disposicion_o_destino_del_paciente", DESTINO_URGENCIAS)
    estandarizar_etiquetas(bl, reporte, b, "muerte_prevenible", MAPEO_MUERTE_PREVENIBLE)
    for col in ["donacion_de_organos", "autopsia"]:
        estandarizar_etiquetas(bl, reporte, b, col, MAPEO_DONACION)
    return bl


def hallazgos_pendientes(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Ambas columnas se excluyen (9 filas informadas; REDCap no las toma). El bloque queda vacío."""
    return eliminar_columnas(bl, reporte, "hallazgos_pendientes", ["hallazgos_clinicos_1", "hallazgos_clinicos_2"],
                             "9 filas informadas; REDCap no las toma")


def por_definir(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """descripcion_del_diagnostico se conserva (comentarios); el resto no está en ningún DDL."""
    return eliminar_columnas(bl, reporte, "por_definir",
                             ["numero_de_registro_del_transporte", "ciudad_hospital_mas_cercano_al_sitio_del_incidente"],
                             SIN_DDL)


def limpieza_estricta_privacidad(texto):
    """Remueve números de teléfono, identificadores y nomenclatura de dirección; preserva las palabras de contexto.
    Un vacío de origen se conserva; lo que queda con 2 letras o menos pasa a "lugar no especificado"."""
    if pd.isna(texto):
        return texto
    texto = " " + str(texto).lower() + " "
    if texto.strip() == "":
        return "lugar no especificado"
    texto = re.sub(r'\d{4,}', ' ', texto)                                          # teléfonos y cédulas
    texto = re.sub(r'(?:[#№º°]|(?<![a-z])(?:no|num|nro)\.?|n°)\s*\d+.*', ' ', texto)  # nomenclatura (# 12-34, no 45)
    texto = re.sub(r'\b(calle|cll|cl|carrera|cra|cr|avenida|ave|av|diagonal|diag|dg|transversal|trans|tv|manzana|mz|'
                   r'casa|cs|apto|apartamento|bloque|bl|lote|lt)\s*\d+[a-z]?\b', r'\1', texto)
    texto = re.sub(r'\b\d+[a-z]?\b', ' ', texto)                                   # números aislados
    texto = re.sub(r'[-–—,./_]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto if len(texto) > 2 else "lugar no especificado"


def identificadores_pendientes(bl: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
    """Direcciones excluidas (como REDCap); direccion_nombre_del_lugar -> lugar_del_evento, limpieza de privacidad y
    clasificación en las 12 etiquetas de REDCap por palabras clave. El texto original se descarta:
    una etiqueta cerrada no puede llevar nombres ni direcciones."""
    b = "identificadores_pendientes"
    bl = eliminar_columnas(bl, reporte, b, ["direccion_linea_1", "direccion_linea_2"],
                           "identificador directo (REDCap tambien excluye la direccion)")
    bl = renombrar_columnas(bl, reporte, b, {"direccion_nombre_del_lugar": "lugar_del_evento"}, ALINEAR)
    original = bl["lugar_del_evento"].copy()
    bl["lugar_del_evento"] = original.map(limpieza_estricta_privacidad).astype("string")
    reporte.registrar_correccion(b, "lugar_del_evento",
                                 "limpieza de privacidad (numeros, telefonos y nomenclatura de direccion)",
                                 int((original.notna() & (original.astype("string") != bl["lugar_del_evento"])).sum()),
                                 "estandarizado")
    mapear_lugar_del_evento(bl, reporte, b, "lugar_del_evento")
    return bl


# Orden de procesamiento = orden del mapeo. Una entrada por bloque de config/mapeo_columnas_excel.yaml.
TRANSFORMACIONES = {
    "informacion_demografica": informacion_demografica, "motivo_de_consulta": motivo_de_consulta,
    "mecanismo_de_lesion": mecanismo_de_lesion, "examen_fisico": examen_fisico, "signos_vitales": signos_vitales,
    "puntuacion_de_severidad": puntuacion_de_severidad, "hospitalizacion": hospitalizacion, "uci": uci,
    "liquidos": liquidos, "atencion_urgencias": atencion_urgencias, "hallazgos_pendientes": hallazgos_pendientes,
    "por_definir": por_definir, "identificadores_pendientes": identificadores_pendientes,
}


def transformar_registro(reg: pd.DataFrame, mapeo: dict[str, list[str]], reporte: ReporteCalidad) -> dict[str, pd.DataFrame]:
    """Divide registro_trauma y transforma cada bloque. Devuelve solo los bloques con columnas propias (los vacíos,
    como signos_vitales y hallazgos_pendientes, no aportan). Falla si el mapeo trae un bloque sin transformación, si
    un bloque pierde el índice de registro_trauma o si una columna queda en dos bloques."""
    sin_funcion = sorted(set(mapeo) - set(TRANSFORMACIONES))
    if sin_funcion:
        raise KeyError(f"Bloques del mapeo sin transformación: {sin_funcion}")
    bloques = {}
    for nombre, bloque in dividir_registro(reg, mapeo).items():
        bloque = TRANSFORMACIONES[nombre](bloque, reporte)
        if not bloque.index.equals(reg.index):
            raise ValueError(f"El bloque {nombre} no conserva el índice de registro_trauma")
        bloques[nombre] = bloque
    columnas = [c for df in bloques.values() for c in df.columns if c != CLAVE]
    repetidas = sorted({c for c in columnas if columnas.count(c) > 1})
    if repetidas:
        raise ValueError(f"Columnas en más de un bloque: {repetidas}")
    return {n: df for n, df in bloques.items() if df.shape[1] > 1}
