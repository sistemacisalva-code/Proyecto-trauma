"""Hojas hijas del Excel histórico (una fila por evento: varias por atención). Cada función recibe la hoja, el reporte y
el contexto compartido y devuelve {tabla: DataFrame}: casi siempre la misma hoja; la hoja 5 se separa por campo CIE-10.
Todo reemplazo de etiquetas y todo renombre quedan contados."""
from dataclasses import dataclass

import pandas as pd

from etl.transform.common.cie10 import PAPEL_A_CAMPO, PAPELES_FUERA_DE_MODELO, mapear_texto_a_cie10
from etl.transform.common.cleaning import (
    convertir_numerico, derivar_duracion_seg, eliminar_columnas, renombrar_columnas)
from etl.transform.common.cronologia import reportar_reglas_ventilador
from etl.transform.common.laboratorio import (
    ESPECIFICACION_NUMERICA, convertir_examenes_numericos, convertir_otras_drogas, convertir_sangre_en_orina,
    convertir_tipo_sangre, reportar_escala_orina, reportar_hematocrito_hemoglobina, reportar_otras_drogas_multiples,
    reportar_unidad_y_rangos_plausibles)
from etl.transform.common.procedimientos import (
    COL_ALTA, COL_DURACION, COL_FIN, COL_INICIO, COL_LLEGADA, reportar_duracion_cero, reportar_duracion_extensa,
    resolver_fechas_procedimiento)
from etl.transform.common.quality import ReporteCalidad
from etl.transform.common.signos_vitales import convertir_signos_vitales, reportar_reglas_signos_vitales
from etl.transform.excel.preparacion import (
    CLAVE, FORMATO_FECHA_HORA, convertir_fecha_con_ventana, estandarizar_etiquetas, mayusculas_sin_espacios,
    regla_cronologica)

ALINEAR = "alinear con el nombre de REDCap"
# Etiquetas que el Excel escribe distinto de REDCap (diccionario de QR-DOM-04, revisado el 2026-10-31)
MAPEO_PARTE_IMAGENES = {"Tórax": "Torax", "Pélvico": "Pelvis",
                        "Tobillo Y Pie No Especificado": "Tobillo y Pie No Especificado"}   # la 'y' minúscula es la de REDCap
# 'Si' ya coincide con REDCap: solo se unifica lo no especificado (no se reusa MAPEO_DONACION, que cambia 'Si' por 'Sí')
MAPEO_PERDIDA_CONCIENCIA = {"No especificado": "Sin especificar"}


@dataclass
class Contexto:
    """Lo que las hojas necesitan de fuera: registro_trauma ya preparado (estancia para procedimientos) y el universo
    CIE-10 (catálogo + lista completa de REDCap)."""
    registro: pd.DataFrame
    universo_cie10: pd.DataFrame


def abuso_sustancias(df, reporte, ctx):
    h = "abuso_sustancias"
    df = renombrar_columnas(df, reporte, h, {"tipo_de_droga": "abuso_de_drogas"}, ALINEAR)
    estandarizar_etiquetas(df, reporte, h, "abuso_de_drogas", {
        "I. Ninguno": "Ninguno", "I.1 Ninguno": "Ninguno", "J. No especificado": "No especificado",
        "G. Tabaco": "Tabaco", "G.1 Tabaco": "Tabaco", "F1. Marihuana": "Marihuana",
        "D. Cocaína": "Cocaína", "D.1 Cocaina": "Cocaína", "F7. Heroína": "Heroína",
        "H. Pegamentos": "Pegamentos", "H.1 Pegamentos": "Pegamentos",
        "A. Anfetaminas": "Anfetaminas", "A1. Anfetaminas": "Anfetaminas", "C. Benzodiasepina": "Benzodiazepinas",
        "C1. Clonazepam": "Clonazepam", "C1. Clonazepan": "Clonazepam", "C2. Clorazepan": "Clorazepam",
        "C7. Lorazepan": "Lorazepam", "C4. Diazepan": "Diazepam", "B1. Fenobarbital": "Fenobarbital",
        "F. Opiaseos/Narcoticos": "Opiáceos/Narcóticos", "F2. Opio": "Opio", "F6. Fentanil": "Fentanilo",
        "F8. Meperidina": "Meperidina", "F10. Morfina": "Morfina",
    }, "etiqueta sin prefijo del formulario y con ortografia corregida")
    return {h: df}


def arma_blanca(df, reporte, ctx):
    h, col = "arma_blanca", "lesiones_por_armas_blancas_laceraciones"
    df = renombrar_columnas(df, reporte, h, {"tipo_de_lesion_penetrante": col}, ALINEAR)
    estandarizar_etiquetas(df, reporte, h, col, {
        "Cortes/Laceraciones": "Cortes / Laceraciones",
        "Heridas penetrantes no especificadas": "Lesión penetrante no especificada"})
    return {h: df}


def arma_fuego(df, reporte, ctx):
    h, col = "arma_fuego", "lesiones_por_arma_de_fuego"
    df = renombrar_columnas(df, reporte, h, {"tipo_de_arma_de_fuego": col}, ALINEAR)
    estandarizar_etiquetas(df, reporte, h, col, {"Rifle, escopeta o arma larga": "Rifle, Escopeta o Arma larga",
                                                 "Pistola/revolver": "Pistola /Revolver"})
    return {h: df}


def calificador_gcs(df, reporte, ctx):
    h = "calificador_gcs"
    estandarizar_etiquetas(df, reporte, h, "calificador_gcs", {
        "GCS Válida: Paciente No Estaba Sedado, Ni Intubado Y No Tenía Obstrucción Del Ojo":
            "GSC Valida: Paciente No Estaba Sedado, Ni Intubado Y No Tenía Obstrucción Del Ojo"})
    return {h: df}


def codigos_cie10(df, reporte, ctx):
    """Texto -> línea CIE-10 de REDCap y UNA TABLA POR CAMPO de REDCap, con la columna con
    el nombre del campo y `cie10_mapeado`. Los papeles fuera de los modelos y las filas sin papel van en tablas aparte."""
    h = "codigos_cie10"
    df = renombrar_columnas(df, reporte, h, {"descripcion": "cie10"}, "linea CIE-10 de REDCap o texto sin pareja")
    mapear_texto_a_cie10(df, reporte, h, "cie10", "cie10_mapeado", universo=ctx.universo_cie10, col_grupo="mecanismo_icd")
    desconocidos = set(df["mecanismo_icd"].dropna()) - set(PAPEL_A_CAMPO) - set(PAPELES_FUERA_DE_MODELO)
    if desconocidos:
        raise ValueError(f"{h}: papeles no previstos en mecanismo_icd: {sorted(desconocidos)}")
    campo = df["mecanismo_icd"].map(PAPEL_A_CAMPO)
    fuera = df["mecanismo_icd"].isin(PAPELES_FUERA_DE_MODELO)
    sin_papel = ~fuera & campo.isna()
    salida = {"codigos_cie10_fuera_de_modelo": df[fuera].reset_index(drop=True)}
    if sin_papel.any():
        salida["codigos_cie10_sin_papel"] = df[sin_papel].reset_index(drop=True)
    for nombre in PAPEL_A_CAMPO.values():
        tabla = df[campo == nombre].drop(columns="mecanismo_icd").reset_index(drop=True)
        salida[nombre] = renombrar_columnas(tabla, reporte, nombre, {"cie10": nombre},
                                            "tabla por campo CIE-10 de REDCap (hoja 5 separada)")
    if sum(len(salida[c]) for c in PAPEL_A_CAMPO.values()) != int(campo.notna().sum()):
        raise ValueError(f"{h}: las tablas por campo no suman las filas con papel")
    return salida


def colisiones(df, reporte, ctx):
    h = "colisiones"
    estandarizar_etiquetas(df, reporte, h, "tipo_de_colision", {
        "Auto, camioneta o van vs. vehiculo de dos o tres ruedas": "Vehículo, camioneta o van vs. vehículo de dos o tres ruedas",
        "Vehículo de dos o tres ruedas vs. animal": "Vehículo de dos o tres ruedas vs animal",
        "Auto, camioneta o van vs. Auto, camioneta o van": "Auto, camioneta o van vs. automóvil, camioneta o van",
        "Auto, camioneta o van vs. bicicleta": "Auto camioneta o van vs. bicicleta",
        "Peatón vs. Bicileta": "Peatón vs. bicicleta",
    })
    return {h: df}


def complicaciones_hospitalizacion(df, reporte, ctx):
    h, col = "complicaciones_hospitalizacion", "cie_10_complicaciones_de_hospitalizacion"
    convertir_fecha_con_ventana(df, reporte, h, "fecha_y_hora_de_complicacion", FORMATO_FECHA_HORA)
    df = renombrar_columnas(df, reporte, h, {"tipo_de_complicacion": col}, ALINEAR)
    mapear_texto_a_cie10(df, reporte, h, col, "complicacion_cie10_mapeada", universo=ctx.universo_cie10)
    return {h: df}


def envenenamiento(df, reporte, ctx):
    h = "envenenamiento"
    df = renombrar_columnas(df, reporte, h, {"tipo_de_envenenamiento": "envenenamiento"}, ALINEAR)
    estandarizar_etiquetas(df, reporte, h, "envenenamiento",
                           {"Mordedura/contacto de serpiente": "Mordedura / Contacto de serpiente"})
    return {h: df}


def imagenes(df, reporte, ctx):
    """parte_del_cuerpo -> parte_del_cuerpo_imagenes (nombre del instrumento imagenes de REDCap); `opcion` se elimina."""
    h = "imagenes"
    df = eliminar_columnas(df, reporte, h, ["opcion"], "sin uso en ningun modelo")
    df = renombrar_columnas(df, reporte, h, {"parte_del_cuerpo": "parte_del_cuerpo_imagenes"}, ALINEAR)
    estandarizar_etiquetas(df, reporte, h, "tipo_de_imagen", {
        "Tomografía axial computarizada (TAC)": "Tomografía Axial Computarizada (TAC)", "Ultra Sonido": "Ultra sonido"})
    estandarizar_etiquetas(df, reporte, h, "parte_del_cuerpo_imagenes", MAPEO_PARTE_IMAGENES)
    return {h: df}


def procedimientos(df, reporte, ctx):
    """Fechas, nombres, MAYÚSCULAS sin CUPS (3.11), resolución de fechas contra la estancia y duración en segundos,
    con las mismas reglas de REDCap (common/procedimientos.py)."""
    h = "procedimientos"
    for col in [COL_INICIO, COL_FIN]:
        convertir_fecha_con_ventana(df, reporte, h, col, FORMATO_FECHA_HORA)
    regla_cronologica(df, reporte, h, "fin del procedimiento anterior al inicio", COL_INICIO, COL_FIN,
                      fecha_si_medianoche=True)
    df = renombrar_columnas(df, reporte, h, {"procedimiento_realizado": "procedimientos"}, ALINEAR)
    df = renombrar_columnas(df, reporte, h, {"lugar": "lugar_procedimiento"}, "nombre definido por el usuario")
    mayusculas_sin_espacios(df, reporte, h, "procedimientos")
    resolver_fechas_procedimiento(df, ctx.registro[[CLAVE, COL_LLEGADA, COL_ALTA]], reporte, h, llave=CLAVE)
    derivar_duracion_seg(df, reporte, h, COL_INICIO, COL_FIN, COL_DURACION)
    reportar_duracion_extensa(df, reporte, h)
    reportar_duracion_cero(df, reporte, h)
    return {h: df}


def procedimientos_prehospitalarios(df, reporte, ctx):
    h = "procedimientos_prehospitalarios"
    mayusculas_sin_espacios(df, reporte, h, "procedimiento_realizado")
    return {h: df}


def quemaduras(df, reporte, ctx):
    h = "quemaduras"
    df = renombrar_columnas(df, reporte, h, {"tipo_de_quemadura": "quemadura"}, ALINEAR)
    estandarizar_etiquetas(df, reporte, h, "quemadura", {
        "Aire caliente/gases": "Aire caliente/Gases", "Eléctrica Voltaje Alto": "Eléctrica voltaje alto",
        "Eléctrica Voltaje Bajo": "Eléctrica voltaje bajo", "Eléctrica no especificada": "Eléctrico no especificado",
        "No especificada": "No especificado"})
    return {h: df}


def signos_vitales(df, reporte, ctx):
    """Fecha, etiquetas de REDCap y reglas comunes. Se audita como `signos_vitales_hoja` (decisión 3.12).
    Ocular y verbal vienen con las etiquetas cambiadas: se intercambian ANTES de validar rangos (decisión 3.16)."""
    h, b = "signos_vitales", "signos_vitales_hoja"
    df = renombrar_columnas(df, reporte, h, {"gcs_ocular": "gcs_verbal", "gcs_verbal": "gcs_ocular"},
                            "etiquetas intercambiadas en el origen: la ocular llega a 5 y la verbal solo a 4")
    convertir_fecha_con_ventana(df, reporte, h, "fecha_y_hora_de_signos_vitales", FORMATO_FECHA_HORA)
    estandarizar_etiquetas(df, reporte, b, "calificador_de_la_frecuencia_respiratoria", {
        "Frecuencia Respiratoria Sin Asistencia": "Frecuencia respiratoria no asistida",
        "Frecuencia Respiratoria Asistida": "Frecuencia respiratoria asistida"})
    estandarizar_etiquetas(df, reporte, b, "avup", {"Unresponsive (No Responde)": "Unresponsive (No responde)",
                                                    "Paciente Responde A Dolor": "Paciente responde al dolor"})
    estandarizar_etiquetas(df, reporte, b, "perdida_de_conciencia", MAPEO_PERDIDA_CONCIENCIA)
    convertir_signos_vitales(df, reporte, b)
    reportar_reglas_signos_vitales(df, reporte, b)
    return {h: df}


def tiempo_uci(df, reporte, ctx):
    """Nombres comunes con el instrumento uci de REDCap; dias_usados_ventilador decimal >= 0 (solo esta hoja)."""
    h = "tiempo_uci"
    inicio, termino = "fecha_y_hora_de_inicio_del_ventilador", "fecha_y_hora_de_termino_del_ventilador"
    df = renombrar_columnas(df, reporte, h, {
        "fecha_y_hora_de_inicio": inicio, "fecha_y_hora_de_termino": termino, "lugar": "lugar_uci",
        "tipo": "tipo_de_ventilador", "uci_dias": "dias_usados_ventilador"},
        "nombre comun con el instrumento uci de REDCap")
    for col in [inicio, termino]:
        convertir_fecha_con_ventana(df, reporte, h, col, FORMATO_FECHA_HORA)
    reportar_reglas_ventilador(df, reporte, h, inicio, termino)    # mismas reglas que el instrumento uci de REDCap
    estandarizar_etiquetas(df, reporte, h, "tipo_de_ventilador", {"Ventilador Mecánico": "Ventilador mecánico"})
    estandarizar_etiquetas(df, reporte, h, "lugar_uci", {
        "UCI Neuroquirúrgica": "UCI neuroquirúrgica", "UCI Quirúrgica / Trauma": "UCI quirúrgica / de trauma",
        "UCI Medicina Interna / Respiratoria": "UCI medicina interna / respiratoria", "UCI de Quemados": "UCI de quemados"})
    convertir_numerico(df, reporte, h, "dias_usados_ventilador", "Float64", rango=(0, float("inf")))
    return {h: df}


def tipo_violencia(df, reporte, ctx):
    h = "tipo_violencia"
    estandarizar_etiquetas(df, reporte, h, "parte_del_cuerpo", {
        "Rodilla Y  Pierna Derecha": "Rodilla Y Pierna Derecha", "Rodilla Y  Pierna Izquierda": "Rodilla Y Pierna Izquierda",
        "Tórax": "Torax", "Tobillo Y Pie No Especificado": "Tobillo y Pie No Especificado"})
    estandarizar_etiquetas(df, reporte, h, "tipo_de_lesion", {
        "Escoriación": "Escoriacion", "Fractura cerrada": "Fractura Cerrada", "Herida penetrante": "Herida Penetrante",
        "Mordedura de animal": "Mordedura De Animal", "Quemadura de tercer grado": "Quemadura De Tercer Grado",
        "Quemadura de segundo grado": "Quemadura De Segundo Grado", "Fractura abierta": "Fractura Abierta",
        "Quemadura de primer grado": "Quemadura De Primer Grado", "Mordedura de humano": "Mordedura De Humano",
        "Picadura de insecto": "Picadura De Insecto", "Función sensorial –": "Función Sensorial -",
        "Función sensorial +": "Función Sensorial +", "Fuerza Motora 2/5": "Fuerza Motora  2/5"})
    return {h: df}


def violencia(df, reporte, ctx):
    h = "violencia"
    return {h: renombrar_columnas(df, reporte, h, {"tipo_de_violencia": "violencia"}, ALINEAR)}


# --- Laboratorio (decisión 3.14) --------------------------------------------------------------------------------
LAB_NOMBRE, LAB_UNIDAD = "nombre_del_laboratorio", "nombre_de_la_unidad_de_laboratorio"
LAB_VALOR, LAB_FECHA = "resultado_de_laboratorio", "fecha_y_hora_de_laboratorio"
EXAMEN_A_REDCAP = {
    "Hct- Hematocrito (%)": "hematocrito", "Hb- Hemoglobina (g/dl)": "hemoglobina", "Plaquetas": "plaquetas",
    "GB.- Glóbulos Blancos": "globulos_blancos", "Na.- Sodio": "na", "K.- Potasio": "k", "Cl.- Cloro": "cl",
    "HCO3- Bicarbonato (mmol/L)": "hco3", "BUN- Nitrógeno úrico (mg/dl)": "bun", "Cr.-Creatinina (mg/dl)": "creatinina",
    "Glucosa (mg/dl)": "glucosa", "TP.- Tiempo de protrombina (segundos)": "tp",
    "TPT.- Tiempo parcial de tromboplastina (segundos)": "tpt", "INR": "inr",
    "PaO2.- Presión parcial de O2 (mm/Hg)": "pao2", "PaCO2.- Presión parcial de CO2 (mm/Hg)": "paco2", "pH": "ph",
    "BE- Exceso de Base (meq/L)": "be", "Déficit de base (mmol/L)": "deficit_de_base", "Lactato (mmol/L)": "lactato",
    "Tipo de Sangre Y Factor RH": "tipo_de_sangre_y_factor_rh", "Sangre en orina": "sangre_en_orina",
    "Otras drogas (orina)": "otras_drogas",
}
NO_EN_REDCAP = {"Alcoholemia (mg/dl)", "Prueba de embarazo", "Tiempo de sangrado (minutos)", "Fibrinógeno (mg/dl)"}
FACTOR_10E12L = 1000    # supuesto: las plaquetas con etiqueta 10E12L son cuentas por uL (283000 -> 283 x10^3/uL)


def laboratorio(df, reporte, ctx):
    """Formato largo (una fila por examen) -> una fila por toma (atención + fecha) con las columnas de REDCap.
    Si el mismo examen se repite en una toma (decisión pendiente), se cuenta y la hoja queda con una fila por examen."""
    h = "laboratorio"
    clave_lab = [CLAVE, LAB_FECHA]
    faltan = {LAB_NOMBRE, LAB_UNIDAD, LAB_VALOR, LAB_FECHA, CLAVE} - set(df.columns)
    if faltan:
        raise KeyError(f"{h}: faltan las columnas {sorted(faltan)}")
    convertir_fecha_con_ventana(df, reporte, h, LAB_FECHA, FORMATO_FECHA_HORA)
    nombre = df[LAB_NOMBRE].astype("string").str.strip()
    desconocidos = set(nombre.dropna()) - set(EXAMEN_A_REDCAP) - NO_EN_REDCAP
    if desconocidos:
        raise ValueError(f"{h}: examenes sin decision (agregarlos a EXAMEN_A_REDCAP o a NO_EN_REDCAP): {sorted(desconocidos)}")
    no_redcap, sin_nombre = nombre.isin(NO_EN_REDCAP), nombre.isna()
    reporte.registrar_correccion(h, LAB_NOMBRE, "examen que no esta en el instrumento laboratorio de REDCap: fila "
                                 "eliminada", int(no_redcap.sum()), "eliminado")
    reporte.registrar_correccion(h, LAB_NOMBRE, "fila sin nombre de examen: eliminada", int(sin_nombre.sum()), "eliminado")
    df = df[~no_redcap & ~sin_nombre].copy()
    variable = df[LAB_NOMBRE].astype("string").str.strip().map(EXAMEN_A_REDCAP)
    unidad = df[LAB_UNIDAD].astype("string").str.strip()

    # Resultado desde la unidad cuando el valor está vacío (tipo de sangre y sangre en orina) y coma decimal a punto
    texto = df[LAB_VALOR].astype("string").str.strip()
    desde_unidad = variable.isin(["tipo_de_sangre_y_factor_rh", "sangre_en_orina"]) & texto.isna() & unidad.notna()
    reporte.registrar_correccion(h, LAB_VALOR, "resultado tomado de la columna de unidad (tipo de sangre y sangre en "
                                 "orina sin valor)", int(desde_unidad.sum()), "corregido")
    texto = texto.where(~desde_unidad, unidad)
    coma = variable.isin(list(ESPECIFICACION_NUMERICA)) & texto.str.fullmatch(r"-?\d+,\d+").fillna(False)
    reporte.registrar_correccion(h, LAB_VALOR, "coma decimal reemplazada por punto", int(coma.sum()), "corregido")
    texto = texto.where(~coma, texto.str.replace(",", ".", regex=False))

    # Plaquetas 10E12L -> 10E3/uL
    plaq = (variable == "plaquetas") & unidad.eq("10E12L").fillna(False)
    plaq_num = pd.to_numeric(texto.where(plaq), errors="coerce")
    reporte.reportar_regla(h, "plaquetas con unidad 10E12L y valor <= 1500 (no parece cuenta por uL)",
                           plaq & plaq_num.notna(), (plaq_num <= 1500).fillna(False), reporte.llaves(df),
                           ["plaquetas (resultado y unidad del examen)"])
    convertidas = (plaq & plaq_num.notna()).fillna(False)   # sin fillna, el NA de los otros exámenes borraría su valor
    reporte.registrar_correccion(h, "plaquetas", f"unidad 10E12L llevada a 10E3/uL (valor / {FACTOR_10E12L})",
                                 int(convertidas.sum()), "corregido")
    texto = texto.where(~convertidas, (plaq_num / FACTOR_10E12L).astype("string"))

    # otras_drogas: POSITIVO o vacío (decisión del usuario 2026-10-21; REDCap no se modifica)
    es_otras = variable == "otras_drogas"
    fuente = texto.fillna(unidad)
    positivo = es_otras & fuente.str.upper().str.contains("POS").fillna(False)
    reporte.registrar_correccion(h, "otras_drogas", "resultado positivo marcado como POSITIVO", int(positivo.sum()),
                                 "estandarizado")
    reporte.registrar_correccion(h, "otras_drogas", "resultado no positivo dejado vacio (decision del usuario)",
                                 int((es_otras & ~positivo & fuente.notna()).sum()), "invalidado a NA")
    texto = texto.mask(positivo, "POSITIVO").mask(es_otras & ~positivo, pd.NA)

    leucocitos = variable == "globulos_blancos"
    reporte.reportar_regla(h, "globulos_blancos con unidad 10E12L (sospechosa)",
                           leucocitos & unidad.notna(), leucocitos & unidad.eq("10E12L").fillna(False),
                           reporte.llaves(df), ["globulos_blancos (resultado y unidad del examen)"])

    # Una columna por variable de REDCap y reglas de REDCap
    lab = df.drop(columns=[LAB_NOMBRE, LAB_UNIDAD, LAB_VALOR])
    variables = sorted(set(variable.dropna()))
    for col in variables:
        lab[col] = texto.where(variable == col)
    convertir_examenes_numericos(lab, reporte, h)
    if "tipo_de_sangre_y_factor_rh" in lab:
        convertir_tipo_sangre(lab, reporte, h)
    if "sangre_en_orina" in lab:
        convertir_sangre_en_orina(lab, reporte, h)
        reportar_escala_orina(lab, reporte, h)
    if "otras_drogas" in lab:
        convertir_otras_drogas(lab, reporte, h)
        reportar_otras_drogas_multiples(lab, reporte, h)
    if "globulos_blancos" in lab:
        reportar_unidad_y_rangos_plausibles(lab, reporte, h)

    repetido = pd.concat([lab[clave_lab], variable.rename("variable")], axis=1).duplicated(keep=False)
    reporte.reportar_regla(h, "mismo examen repetido en la misma toma (atencion + fecha); decision pendiente",
                           variable.notna(), repetido, reporte.llaves(df),
                           ["examen de laboratorio (nombre y fecha de la toma)"])
    if repetido.any():
        return {h: lab}
    otras = [c for c in lab.columns if c not in clave_lab + variables]
    if otras:
        distintas = lab.groupby(clave_lab, dropna=False)[otras].nunique(dropna=False).max()
        if (distintas > 1).any():
            raise ValueError(f"{h}: columnas que cambian dentro de una toma: {list(distintas[distintas > 1].index)}")
    filas_antes = len(lab)
    lab = lab.groupby(clave_lab, dropna=False, sort=False).first().reset_index()
    reporte.registrar_correccion(h, "(filas)", "filas de examenes juntadas en una fila por toma (atencion + fecha)",
                                 filas_antes - len(lab), "agrupado")
    if {"hematocrito", "hemoglobina"} <= set(lab.columns):
        reportar_hematocrito_hemoglobina(lab, reporte, h)
    return {h: lab}


# Fechas de evento que deben caer en la estancia (llegada -> alta, con margen): las mismas de REDCap
# (redcap/cronologia.py: FECHAS_DE_EVENTO) más la fecha de complicación, que REDCap no registra.
FECHAS_DE_EVENTO = (
    ("signos_vitales", "fecha_y_hora_de_signos_vitales"),
    ("laboratorio", LAB_FECHA),
    ("procedimientos", COL_INICIO),
    ("procedimientos", COL_FIN),
    ("tiempo_uci", "fecha_y_hora_de_inicio_del_ventilador"),
    ("tiempo_uci", "fecha_y_hora_de_termino_del_ventilador"),
    ("complicaciones_hospitalizacion", "fecha_y_hora_de_complicacion"),
)

# Una entrada por hoja hija de la carga histórica (EXCEL_SHEETS_CONFIG, sin registro_trauma)
TRANSFORMACIONES = {
    "abuso_sustancias": abuso_sustancias, "arma_blanca": arma_blanca, "arma_fuego": arma_fuego,
    "calificador_gcs": calificador_gcs, "codigos_cie10": codigos_cie10, "colisiones": colisiones,
    "complicaciones_hospitalizacion": complicaciones_hospitalizacion, "envenenamiento": envenenamiento,
    "imagenes": imagenes, "procedimientos": procedimientos,
    "procedimientos_prehospitalarios": procedimientos_prehospitalarios, "quemaduras": quemaduras,
    "signos_vitales": signos_vitales, "tiempo_uci": tiempo_uci, "tipo_violencia": tipo_violencia,
    "violencia": violencia, "laboratorio": laboratorio,
}
