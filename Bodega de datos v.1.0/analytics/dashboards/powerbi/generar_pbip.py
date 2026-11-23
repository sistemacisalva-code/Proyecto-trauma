"""Genera el proyecto de Power BI (PBIP: modelo TMDL + reporte PBIR) del tablero de trauma_completo.

El proyecto se genera SIN DATOS: solo define tablas, columnas, relaciones, medidas y visuales.
Los datos llegan cuando el autor abre el proyecto en Power BI Desktop, escribe sus credenciales
y actualiza. Por eso la salida va siempre FUERA del repositorio (.gitignore excluye *.pbip,
*.Report/ y *.SemanticModel/): despues de actualizar, la cache del proyecto contiene datos.

Fuentes de la definicion:
  - Estructura: database/schema/02_tables_completo.sql y 02_etl_control.sql
  - Consultas: analytics/queries/conexion_power_bi.sql (estandar) y conexion_power_bi_admin.sql (admin)
  - Medidas: analytics/dashboards/powerbi/medidas_dax.md
  - Paginas: docs/tecnico/06_tablero_power_bi.md (seccion 6)

Uso:
  python generar_pbip.py <carpeta_salida> [--variante estandar|admin] [--sin-control]
    --variante admin  incluye el texto libre (copia restringida, ver seccion 12 del diseno)
    --sin-control     omite la pagina de cargas (si el lector aun no tiene acceso a etl_control)
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

ESQ = "trauma_completo"
SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
S1, S2 = "#2a78d6", "#eb6834"

# ============================================================
# 1. MODELO SEMANTICO
# ============================================================
# Tipos: INTEGER -> int64, NUMERIC -> double, TEXT -> string, DATE/TIMESTAMPTZ -> dateTime, BOOLEAN -> boolean
I, D, S, F, B = "int64", "double", "string", "dateTime", "boolean"

DIMS = {
    "dim_paciente": [("paciente_id", I), ("quinquenio", S), ("quinquenio_orden", I), ("estado_civil", S),
                     ("genero", S), ("nacionalidad", S), ("tipo_seguro", S), ("paciente_asegurado", S)],
    "dim_evento_trauma": [("evento_id", I), ("consumo_alcohol", S), ("violencia", S), ("envenenamiento", S),
                          ("lugar_evento", S)],
    "dim_tiempo": [("tiempo_id", I), ("fecha", F), ("dia", I), ("mes", I), ("nombre_mes", S), ("trimestre", I),
                   ("anio", I), ("dia_semana", S), ("es_festivo", S)],
    "dim_horario": [("horario_id", I), ("hora_larga", S), ("hora", I), ("minuto", I), ("intervalo", S)],
    "dim_caida": [("caida_id", I), ("caida", S), ("tipo_superficie", S)],
    "dim_quemadura": [("quemadura_id", I), ("quemadura", S), ("grado_quemadura", S)],
    "dim_accidente_transito": [("accidente_id", I), ("velocidad_colision", S), ("tipo_vehiculo", S),
                               ("ocupante", S), ("tipo_colision", S)],
    "dim_armas": [("armas_id", I), ("lesion_arma_fuego", S), ("lesion_arma_blanca", S)],
    "dim_desenlace": [("desenlace_id", I), ("disposicion_paciente", S), ("muerte_prevenible", S),
                      ("donacion_organos", S), ("autopsia", S)],
    "dim_calificador_signos": [("calificador_signos_id", I), ("perdida_conciencia", S), ("avup", S),
                               ("calificador_gcs", S), ("calificador_frecuencia_respiratoria", S)],
    "dim_parte_cuerpo_lesion": [("parte_cuerpo_lesion_id", I), ("parte_cuerpo", S)],
    "dim_mecanismo_primario": [("mecanismo_primario_id", I), ("mecanismo_primario", S)],
    "dim_tipo_lesion": [("tipo_lesion_id", I), ("tipo_lesion", S)],
    "dim_cie_10": [("cie_10_id", I), ("cie_10", S)],
    "dim_sustancia": [("sustancia_id", I), ("sustancia", S)],
    "dim_procedimiento": [("procedimiento_id", I), ("procedimientos", S)],
    "dim_imagen": [("imagen_id", I), ("tipo_imagen", S), ("parte_cuerpo", S)],
}

PUENTES_NAVEGADOR = {
    "bridge_atencion_lesion": [("fact_id", I), ("secuencia", I), ("parte_cuerpo_lesion_id", I),
                               ("mecanismo_primario_id", I), ("tipo_lesion_id", I)],
    "bridge_atencion_sustancia": [("fact_id", I), ("sustancia_id", I)],
    "bridge_atencion_procedimiento": [("fact_id", I), ("secuencia", I), ("procedimiento_id", I),
                                      ("fecha_inicio_id", I), ("hora_inicio_id", I), ("duracion_seg", I)],
}

FACT_CLAVES = [("fact_id", I), ("fecha_admision_id", I), ("fecha_hospitalizacion_id", I), ("fecha_alta_id", I),
               ("hora_alta_id", I), ("paciente_id", I), ("evento_id", I), ("caida_id", I), ("quemadura_id", I),
               ("accidente_id", I), ("armas_id", I), ("desenlace_id", I), ("calificador_signos_id", I)]
FACT_MEDIDAS = [("gcs_ocular", I), ("gcs_verbal", I), ("gcs_motor", I), ("presion_sistolica", D),
                ("presion_diastolica", D), ("frecuencia_cardiaca", D), ("frecuencia_respiratoria", D),
                ("saturacion_o2", D), ("temperatura_c", D), ("iss", D), ("cabeza", I), ("cara", I), ("torax", I),
                ("abdomen", I), ("extremidades", I), ("externo", I), ("dias_hospitalizacion", D), ("uci_dias", D),
                ("sangre_l", D)]
FACT_ADMIN_EXTRA = [("trauma_register_id", S), ("peso", D), ("altura", D), ("altura_metros", D), ("scq", D),
                    ("duracion_perdida_conciencia", D), ("pao2", D), ("paco2", D), ("motivo_consulta", S),
                    ("otras_sustancias_de_abuso", S), ("detalles_hospitalizacion", S)]


def consultas_sql(admin):
    """Mismas consultas que analytics/queries/conexion_power_bi*.sql (una linea cada una)."""
    fact_cols = [c for c, _ in FACT_CLAVES + FACT_MEDIDAS] + ([c for c, _ in FACT_ADMIN_EXTRA] if admin else [])
    q = {
        "fact_trauma": (f"SELECT {', '.join(fact_cols)} FROM {ESQ}.fact_trauma",
                        FACT_CLAVES + FACT_MEDIDAS + (FACT_ADMIN_EXTRA if admin else [])),
        "bridge_atencion_imagen": (
            f"SELECT fact_id, secuencia, imagen_id{', descripcion_imagen' if admin else ''} FROM {ESQ}.bridge_atencion_imagen",
            [("fact_id", I), ("secuencia", I), ("imagen_id", I)] + ([("descripcion_imagen", S)] if admin else [])),
        "bridge_atencion_cie_10": (
            f"SELECT atencion_cie_10_id, fact_id, cie_10_id, rol{', texto_origen' if admin else ''} FROM {ESQ}.bridge_atencion_cie_10",
            [("atencion_cie_10_id", I), ("fact_id", I), ("cie_10_id", I), ("rol", S)]
            + ([("texto_origen", S)] if admin else [])),
        "bridge_atencion_complicacion": (
            f"SELECT complicacion_id, fact_id, cie_10_id, lugar_complicacion{', texto_origen' if admin else ''} "
            f"FROM {ESQ}.bridge_atencion_complicacion",
            [("complicacion_id", I), ("fact_id", I), ("cie_10_id", I), ("lugar_complicacion", S)]
            + ([("texto_origen", S)] if admin else [])),
    }
    return q


def consultas_control(admin):
    carga = [("id", I), ("modelo", S), ("fuente", S)] + ([("run_id_staging", S)] if admin else []) + [
        ("filas_origen", I), ("filas_cargadas", I), ("filas_no_usadas", I), ("filas_cuarentena", I),
        ("atenciones_nuevas", I), ("atenciones_modificadas", I), ("atenciones_sin_cambio", I),
        ("atenciones_eliminadas", I)] + ([("ruta_cuarentena", S)] if admin else []) + [
        ("exitosa", B), ("ejecutado_en", F)]
    calidad = [("id", I), ("modelo", S), ("veredicto", S), ("reglas_cumplen", I), ("reglas_advierten", I),
               ("reglas_fallan", I)] + ([("ruta_reporte", S)] if admin else []) + [("ejecutado_en", F)]
    return {
        "carga": (f"SELECT {', '.join(c for c, _ in carga)} FROM etl_control.carga", carga),
        "calidad": (f"SELECT {', '.join(c for c, _ in calidad)} FROM etl_control.calidad", calidad),
    }


# Columnas calculadas: (tabla, nombre, tipo, DAX, formato, ordenar_por)
CALCULADAS = [
    ("fact_trauma", "gcs_total", I, "IF(NOT ISBLANK(fact_trauma[gcs_ocular]) && NOT ISBLANK(fact_trauma[gcs_verbal]) && NOT ISBLANK(fact_trauma[gcs_motor]), fact_trauma[gcs_ocular] + fact_trauma[gcs_verbal] + fact_trauma[gcs_motor])", "0", None),
    ("fact_trauma", "indice_choque", D, "IF(NOT ISBLANK(fact_trauma[frecuencia_cardiaca]) && NOT ISBLANK(fact_trauma[presion_sistolica]) && fact_trauma[presion_sistolica] > 0, DIVIDE(fact_trauma[frecuencia_cardiaca], fact_trauma[presion_sistolica]))", "0.00", None),
    ("fact_trauma", "rango_iss_orden", I, 'SWITCH(TRUE(), ISBLANK(fact_trauma[iss]) || fact_trauma[iss] < 1, 5, fact_trauma[iss] <= 8, 1, fact_trauma[iss] <= 15, 2, fact_trauma[iss] <= 24, 3, 4)', "0", None),
    ("fact_trauma", "rango_iss", S, 'SWITCH(TRUE(), ISBLANK(fact_trauma[iss]) || fact_trauma[iss] < 1, "Sin ISS", fact_trauma[iss] <= 8, "1–8", fact_trauma[iss] <= 15, "9–15", fact_trauma[iss] <= 24, "16–24", "25 o más")', None, "rango_iss_orden"),
    ("fact_trauma", "dias_admision_alta", I, "VAR admision = LOOKUPVALUE(dim_tiempo[fecha], dim_tiempo[tiempo_id], fact_trauma[fecha_admision_id]) VAR alta = LOOKUPVALUE(dim_tiempo[fecha], dim_tiempo[tiempo_id], fact_trauma[fecha_alta_id]) RETURN IF(NOT ISBLANK(admision) && NOT ISBLANK(alta), INT(alta - admision))", "0", None),
    ("dim_desenlace", "grupo_destino", S, 'VAR d = TRIM(dim_desenlace[disposicion_paciente]) RETURN SWITCH(TRUE(), ISBLANK(d) || d IN {"Sin dato", "Desconocido"}, "Sin información", d IN {"Fallece (Morgue)", "Murió antes de la llegada", "Murió en el Departamento de emergencias"}, "Fallecido", d = "Admitido a la UCI", "UCI", d = "Sala de Operaciones", "Quirófano", LEFT(d, 9) = "Internado", "Hospitalización", d IN {"Domicilio", "Consulta externa"}, "Alta", LEFT(d, 8) = "Referido" || LEFT(d, 11) = "Transferido", "Traslado a otro hospital", "Otros")', None, None),
    ("dim_armas", "con_arma_fuego", S, 'IF(NOT ISBLANK(dim_armas[lesion_arma_fuego]) && NOT (dim_armas[lesion_arma_fuego] IN {"No aplica", "Sin dato"}), "Sí", "No")', None, None),
    ("dim_armas", "con_arma_cortopunzante", S, 'IF(NOT ISBLANK(dim_armas[lesion_arma_blanca]) && NOT (dim_armas[lesion_arma_blanca] IN {"No aplica", "Sin dato"}), "Sí", "No")', None, None),
    ("dim_tiempo", "tipo_dia", S, 'SWITCH(TRUE(), dim_tiempo[es_festivo] = "SI", "Festivos", WEEKDAY(dim_tiempo[fecha], 2) >= 6, "Sábado y domingo", "Lunes a viernes")', None, None),
    ("dim_tiempo", "dia_semana_orden", I, "WEEKDAY(dim_tiempo[fecha], 2)", "0", None),
    ("dim_tiempo", "anio_mes", S, 'FORMAT(dim_tiempo[fecha], "yyyy-mm")', None, None),
]
ORDEN_COLUMNAS = {("dim_paciente", "quinquenio"): "quinquenio_orden", ("dim_tiempo", "dia_semana"): "dia_semana_orden",
                  ("dim_tiempo", "nombre_mes"): "mes"}

MEC = 'SELECTEDVALUE(Mecanismos[mecanismo])'
TRANSITO = ('dim_accidente_transito[velocidad_colision] <> "No aplica", '
            'NOT ISBLANK(dim_accidente_transito[velocidad_colision])')


def por_mecanismo(base):
    return (f'SWITCH({MEC}, '
            f'"Caída", CALCULATE({base}, dim_caida[caida] <> "No aplica", NOT ISBLANK(dim_caida[caida])), '
            f'"Quemadura", CALCULATE({base}, dim_quemadura[quemadura] <> "No aplica", NOT ISBLANK(dim_quemadura[quemadura])), '
            f'"Tránsito: motocicleta", CALCULATE({base}, {TRANSITO}, dim_accidente_transito[tipo_vehiculo] = "Motocicleta"), '
            f'"Tránsito: otro vehículo", CALCULATE({base}, {TRANSITO}, dim_accidente_transito[tipo_vehiculo] <> "Motocicleta"), '
            f'"Arma de fuego", CALCULATE({base}, dim_armas[con_arma_fuego] = "Sí"), '
            f'"Arma cortopunzante", CALCULATE({base}, dim_armas[con_arma_cortopunzante] = "Sí"))')


def ultima_calidad(col):
    return ('VAR ultima = CALCULATE(MAX(calidad[ejecutado_en]), calidad[modelo] = "completo") RETURN '
            f'CALCULATE(SUM(calidad[{col}]), calidad[ejecutado_en] = ultima, calidad[modelo] = "completo")')


PCT, ENT, DEC = "0.0%", "#,0", "#,0.0"
# Medidas: (carpeta, nombre, DAX, formato)
MEDIDAS = [
    ("Volumen", "Atenciones", "DISTINCTCOUNT(fact_trauma[fact_id])", ENT),
    ("Volumen", "% de atenciones", "DIVIDE([Atenciones], CALCULATE([Atenciones], ALLSELECTED(dim_paciente)))", PCT),
    ("Volumen", "Promedio diario", "VAR primera = CALCULATE(MIN(dim_tiempo[fecha]), fact_trauma) VAR ultima = CALCULATE(MAX(dim_tiempo[fecha]), fact_trauma) VAR dias = COUNTROWS(FILTER(VALUES(dim_tiempo[fecha]), dim_tiempo[fecha] >= primera && dim_tiempo[fecha] <= ultima)) RETURN DIVIDE([Atenciones], dias)", DEC),
    ("Volumen", "Atenciones por mecanismo", por_mecanismo("[Atenciones]"), ENT),
    ("Severidad", "ISS promedio", "AVERAGE(fact_trauma[iss])", DEC),
    ("Severidad", "Atenciones con ISS", "CALCULATE([Atenciones], fact_trauma[iss] >= 1)", ENT),
    ("Severidad", "% ISS ≥ 16", "DIVIDE(CALCULATE([Atenciones], fact_trauma[iss] >= 16), [Atenciones con ISS])", PCT),
    ("Severidad", "Atenciones con GCS", "CALCULATE([Atenciones], NOT ISBLANK(fact_trauma[gcs_total]))", ENT),
    ("Severidad", "% GCS < 9", "DIVIDE(CALCULATE([Atenciones], fact_trauma[gcs_total] < 9, NOT ISBLANK(fact_trauma[gcs_total])), [Atenciones con GCS])", PCT),
    ("Severidad", "% PAS < 90", "DIVIDE(CALCULATE([Atenciones], fact_trauma[presion_sistolica] < 90, NOT ISBLANK(fact_trauma[presion_sistolica])), CALCULATE([Atenciones], NOT ISBLANK(fact_trauma[presion_sistolica])))", PCT),
    ("Severidad", "% índice de choque > 0,9", "DIVIDE(CALCULATE([Atenciones], fact_trauma[indice_choque] > 0.9), CALCULATE([Atenciones], NOT ISBLANK(fact_trauma[indice_choque])))", PCT),
    ("Severidad", "PAS promedio", "AVERAGE(fact_trauma[presion_sistolica])", DEC),
    ("Severidad", "PAD promedio", "AVERAGE(fact_trauma[presion_diastolica])", DEC),
    ("Severidad", "FC promedio", "AVERAGE(fact_trauma[frecuencia_cardiaca])", DEC),
    ("Severidad", "FR promedio", "AVERAGE(fact_trauma[frecuencia_respiratoria])", DEC),
    ("Severidad", "Saturación promedio", "AVERAGE(fact_trauma[saturacion_o2])", DEC),
    ("Severidad", "Temperatura promedio", "AVERAGE(fact_trauma[temperatura_c])", DEC),
    ("Severidad", "GCS promedio", "AVERAGE(fact_trauma[gcs_total])", DEC),
    ("Severidad", "AIS cabeza", "AVERAGE(fact_trauma[cabeza])", DEC),
    ("Severidad", "AIS cara", "AVERAGE(fact_trauma[cara])", DEC),
    ("Severidad", "AIS tórax", "AVERAGE(fact_trauma[torax])", DEC),
    ("Severidad", "AIS abdomen", "AVERAGE(fact_trauma[abdomen])", DEC),
    ("Severidad", "AIS extremidades", "AVERAGE(fact_trauma[extremidades])", DEC),
    ("Severidad", "AIS externo", "AVERAGE(fact_trauma[externo])", DEC),
    ("Resultado", "Fallecidos", 'CALCULATE([Atenciones], dim_desenlace[grupo_destino] = "Fallecido")', ENT),
    ("Resultado", "Atenciones con destino conocido", 'CALCULATE([Atenciones], dim_desenlace[grupo_destino] <> "Sin información")', ENT),
    ("Resultado", "Mortalidad", "DIVIDE([Fallecidos], [Atenciones con destino conocido])", PCT),
    ("Resultado", "Mortalidad por mecanismo", por_mecanismo("[Mortalidad]"), PCT),
    ("Recursos y estancia", "Atenciones con UCI", "CALCULATE([Atenciones], fact_trauma[uci_dias] > 0)", ENT),
    ("Recursos y estancia", "% con UCI", "DIVIDE([Atenciones con UCI], CALCULATE([Atenciones], NOT ISBLANK(fact_trauma[uci_dias])))", PCT),
    ("Recursos y estancia", "Atenciones con procedimiento", "DISTINCTCOUNT(bridge_atencion_procedimiento[fact_id])", ENT),
    ("Recursos y estancia", "% con procedimiento", "DIVIDE([Atenciones con procedimiento], [Atenciones])", PCT),
    ("Recursos y estancia", "Atenciones con imagen", "DISTINCTCOUNT(bridge_atencion_imagen[fact_id])", ENT),
    ("Recursos y estancia", "% con imagen", "DIVIDE([Atenciones con imagen], [Atenciones])", PCT),
    ("Recursos y estancia", "Transfundidos", "CALCULATE([Atenciones], fact_trauma[sangre_l] > 0)", ENT),
    ("Recursos y estancia", "% transfundidos", "DIVIDE([Transfundidos], CALCULATE([Atenciones], NOT ISBLANK(fact_trauma[sangre_l])))", PCT),
    ("Recursos y estancia", "Litros de sangre", "SUM(fact_trauma[sangre_l])", DEC),
    ("Recursos y estancia", "Días de hospitalización (promedio)", "AVERAGE(fact_trauma[dias_hospitalizacion])", DEC),
    ("Recursos y estancia", "Días de UCI (promedio)", "AVERAGE(fact_trauma[uci_dias])", DEC),
    ("Recursos y estancia", "Días de hospitalización por mes de alta", "CALCULATE([Días de hospitalización (promedio)], USERELATIONSHIP(fact_trauma[fecha_alta_id], dim_tiempo[tiempo_id]))", DEC),
    ("Recursos y estancia", "Días de UCI por mes de alta", "CALCULATE([Días de UCI (promedio)], USERELATIONSHIP(fact_trauma[fecha_alta_id], dim_tiempo[tiempo_id]))", DEC),
    ("Recursos y estancia", "Estancia admisión–alta (promedio)", "AVERAGE(fact_trauma[dias_admision_alta])", DEC),
    ("Diagnósticos y contexto", "Atenciones con diagnóstico", 'CALCULATE(DISTINCTCOUNT(bridge_atencion_cie_10[fact_id]), bridge_atencion_cie_10[rol] = "diagnostico")', ENT),
    ("Diagnósticos y contexto", "Atenciones con comorbilidad", 'CALCULATE(DISTINCTCOUNT(bridge_atencion_cie_10[fact_id]), bridge_atencion_cie_10[rol] = "comorbilidad")', ENT),
    ("Diagnósticos y contexto", "Atenciones con complicación", "DISTINCTCOUNT(bridge_atencion_complicacion[fact_id])", ENT),
    ("Diagnósticos y contexto", "Atenciones con lesión", "DISTINCTCOUNT(bridge_atencion_lesion[fact_id])", ENT),
    ("Diagnósticos y contexto", "Atenciones con sustancia", "DISTINCTCOUNT(bridge_atencion_sustancia[fact_id])", ENT),
    ("Diagnósticos y contexto", "% con sustancia", "DIVIDE([Atenciones con sustancia], [Atenciones])", PCT),
    ("Diagnósticos y contexto", "% violencia", 'DIVIDE(CALCULATE([Atenciones], dim_evento_trauma[violencia] IN {"Abuso físico", "Abuso psicológico", "Abuso sexual", "Sospecha de violencia"}), [Atenciones])', PCT),
    ("Diagnósticos y contexto", "% autolesión", 'DIVIDE(CALCULATE([Atenciones], dim_evento_trauma[violencia] = "Intento de suicidio"), [Atenciones])', PCT),
    ("Diagnósticos y contexto", "% consumo de alcohol", 'DIVIDE(CALCULATE([Atenciones], dim_evento_trauma[consumo_alcohol] = "Si"), CALCULATE([Atenciones], dim_evento_trauma[consumo_alcohol] IN {"Si", "No"}))', PCT),
    ("Diagnósticos y contexto", "Cobertura consumo de alcohol", 'DIVIDE(CALCULATE([Atenciones], dim_evento_trauma[consumo_alcohol] IN {"Si", "No"}), [Atenciones])', PCT),
    ("Diagnósticos y contexto", "% trauma penetrante", 'DIVIDE(CALCULATE([Atenciones con lesión], dim_mecanismo_primario[mecanismo_primario] = "Penetrante"), CALCULATE([Atenciones con lesión], dim_mecanismo_primario[mecanismo_primario] <> "Sin dato"))', PCT),
    ("Cobertura", "Cobertura del mecanismo primario", 'DIVIDE(CALCULATE([Atenciones con lesión], dim_mecanismo_primario[mecanismo_primario] <> "Sin dato"), [Atenciones])', PCT),
    ("Cobertura", "Cobertura arma de fuego", 'DIVIDE(CALCULATE([Atenciones], dim_armas[lesion_arma_fuego] <> "Sin dato"), [Atenciones])', PCT),
    ("Cobertura", "Cobertura arma cortopunzante", 'DIVIDE(CALCULATE([Atenciones], dim_armas[lesion_arma_blanca] <> "Sin dato"), [Atenciones])', PCT),
    ("Demografía", "Pirámide", 'IF(SELECTEDVALUE(dim_paciente[genero]) = "Masculino", -[% de atenciones], [% de atenciones])', "0.0%;0.0%"),
    ("Demografía", "% hombres", 'DIVIDE(CALCULATE([Atenciones], dim_paciente[genero] = "Masculino"), [Atenciones])', PCT),
    ("Demografía", "% mujeres", 'DIVIDE(CALCULATE([Atenciones], dim_paciente[genero] = "Femenino"), [Atenciones])', PCT),
    # Excluye "Sin dato" y vacios: con todos los anios, las atenciones sin edad serian el grupo mas grande.
    ("Demografía", "Quinquenio más frecuente", 'VAR quinquenios = FILTER(VALUES(dim_paciente[quinquenio]), NOT ISBLANK(dim_paciente[quinquenio]) && dim_paciente[quinquenio] <> "Sin dato") RETURN MAXX(TOPN(1, quinquenios, [Atenciones]), dim_paciente[quinquenio])', None),
]
MEDIDAS_CONTROL = [
    ("Cargas", "Última carga exitosa", 'CALCULATE(MAX(carga[ejecutado_en]), carga[exitosa] = TRUE(), carga[modelo] = "completo")', "yyyy-mm-dd hh:nn"),
    ("Cargas", "Último veredicto", 'VAR ultima = CALCULATE(MAX(calidad[ejecutado_en]), calidad[modelo] = "completo") RETURN CALCULATE(SELECTEDVALUE(calidad[veredicto]), calidad[ejecutado_en] = ultima, calidad[modelo] = "completo")', None),
    ("Cargas", "Reglas que cumplen (última)", ultima_calidad("reglas_cumplen"), ENT),
    ("Cargas", "Reglas que advierten (última)", ultima_calidad("reglas_advierten"), ENT),
    ("Cargas", "Reglas que fallan (última)", ultima_calidad("reglas_fallan"), ENT),
]

# Relaciones: (desde tabla.columna [muchos], hasta tabla.columna [uno], activa, ambos_sentidos)
RELACIONES = [
    ("fact_trauma.fecha_admision_id", "dim_tiempo.tiempo_id", True, False),
    ("fact_trauma.fecha_alta_id", "dim_tiempo.tiempo_id", False, False),
    ("fact_trauma.fecha_hospitalizacion_id", "dim_tiempo.tiempo_id", False, False),
    ("fact_trauma.hora_alta_id", "dim_horario.horario_id", True, False),
    ("fact_trauma.paciente_id", "dim_paciente.paciente_id", True, False),
    ("fact_trauma.evento_id", "dim_evento_trauma.evento_id", True, False),
    ("fact_trauma.caida_id", "dim_caida.caida_id", True, False),
    ("fact_trauma.quemadura_id", "dim_quemadura.quemadura_id", True, False),
    ("fact_trauma.accidente_id", "dim_accidente_transito.accidente_id", True, False),
    ("fact_trauma.armas_id", "dim_armas.armas_id", True, False),
    ("fact_trauma.desenlace_id", "dim_desenlace.desenlace_id", True, False),
    ("fact_trauma.calificador_signos_id", "dim_calificador_signos.calificador_signos_id", True, False),
    ("bridge_atencion_lesion.fact_id", "fact_trauma.fact_id", True, True),
    ("bridge_atencion_lesion.parte_cuerpo_lesion_id", "dim_parte_cuerpo_lesion.parte_cuerpo_lesion_id", True, False),
    ("bridge_atencion_lesion.mecanismo_primario_id", "dim_mecanismo_primario.mecanismo_primario_id", True, False),
    ("bridge_atencion_lesion.tipo_lesion_id", "dim_tipo_lesion.tipo_lesion_id", True, False),
    ("bridge_atencion_imagen.fact_id", "fact_trauma.fact_id", True, False),
    ("bridge_atencion_imagen.imagen_id", "dim_imagen.imagen_id", True, False),
    ("bridge_atencion_cie_10.fact_id", "fact_trauma.fact_id", True, False),
    ("bridge_atencion_cie_10.cie_10_id", "dim_cie_10.cie_10_id", True, False),
    ("bridge_atencion_complicacion.fact_id", "fact_trauma.fact_id", True, False),
    ("bridge_atencion_complicacion.cie_10_id", "dim_cie_10.cie_10_id", True, False),
    ("bridge_atencion_sustancia.fact_id", "fact_trauma.fact_id", True, False),
    ("bridge_atencion_sustancia.sustancia_id", "dim_sustancia.sustancia_id", True, False),
    ("bridge_atencion_procedimiento.fact_id", "fact_trauma.fact_id", True, False),
    ("bridge_atencion_procedimiento.procedimiento_id", "dim_procedimiento.procedimiento_id", True, False),
    # Sin relacion: bridge_atencion_procedimiento.fecha_inicio_id/hora_inicio_id (crearia dos caminos
    # desde dim_tiempo y dim_horario hasta el puente: ambiguedad).
]


def ident(nombre):
    """Nombre TMDL: entre comillas simples si no es un identificador simple."""
    return nombre if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nombre) else "'" + nombre.replace("'", "''") + "'"


def es_clave(tabla, col):
    return col.endswith("_id") and not (tabla == "fact_trauma" and col == "fact_id")


def tmdl_columna(tabla, col, tipo, orden=None):
    lin = [f"\tcolumn {ident(col)}", f"\t\tdataType: {tipo}"]
    if tipo == I:
        lin.append("\t\tformatString: 0")
    if tipo == F:
        lin.append("\t\tformatString: yyyy-mm-dd" if tabla == "dim_tiempo" else "\t\tformatString: yyyy-mm-dd hh:nn")
    if es_clave(tabla, col) or col.endswith("_orden"):
        lin.append("\t\tisHidden")
    lin.append("\t\tsummarizeBy: none")
    lin.append(f"\t\tsourceColumn: {col}")
    if orden:
        lin.append(f"\t\tsortByColumn: {orden}")
    return "\n".join(lin)


def tmdl_m(tabla, consulta=None):
    if consulta:
        src = f'PostgreSQL.Database(Servidor, BaseDatos, [Query="{consulta}"])'
        return f"\tpartition {tabla} = m\n\t\tmode: import\n\t\tsource = {src}"
    esquema = "etl_control" if tabla in ("carga", "calidad") else ESQ
    return (f"\tpartition {tabla} = m\n\t\tmode: import\n\t\tsource =\n"
            f"\t\t\t\tlet\n"
            f"\t\t\t\t    Origen = PostgreSQL.Database(Servidor, BaseDatos),\n"
            f"\t\t\t\t    Datos = Origen{{[Schema=\"{esquema}\", Item=\"{tabla}\"]}}[Data]\n"
            f"\t\t\t\tin\n"
            f"\t\t\t\t    Datos")


def tmdl_tabla(tabla, columnas, consulta=None):
    partes = [f"table {tabla}", ""]
    for col, tipo in columnas:
        partes += [tmdl_columna(tabla, col, tipo, ORDEN_COLUMNAS.get((tabla, col))), ""]
    for t, nombre, tipo, dax, fmt, orden in CALCULADAS:
        if t != tabla:
            continue
        lin = [f"\tcolumn {ident(nombre)} = {dax}", f"\t\tdataType: {tipo}"]
        if fmt:
            lin.append(f"\t\tformatString: {fmt}")
        if nombre.endswith("_orden"):
            lin.append("\t\tisHidden")
        lin.append("\t\tsummarizeBy: none")
        if orden:
            lin.append(f"\t\tsortByColumn: {orden}")
        partes += ["\n".join(lin), ""]
    partes += [tmdl_m(tabla, consulta), ""]
    return "\n".join(partes)


def tmdl_medidas(medidas):
    partes = ["table Medidas", ""]
    for carpeta, nombre, dax, fmt in medidas:
        lin = [f"\tmeasure {ident(nombre)} = {dax}"]
        if fmt:
            lin.append(f"\t\tformatString: {fmt}")
        lin.append(f"\t\tdisplayFolder: {carpeta}")
        partes += ["\n".join(lin), ""]
    partes += ["\tcolumn aux", "\t\tdataType: int64", "\t\tisHidden", "\t\tsummarizeBy: none",
               "\t\tsourceColumn: [aux]", "",
               "\tpartition Medidas = calculated", "\t\tmode: import", '\t\tsource = ROW("aux", 0)', ""]
    return "\n".join(partes)


def tmdl_mecanismos():
    filas = ", ".join(f'{{"{m}", {i}}}' for i, m in enumerate(
        ["Caída", "Quemadura", "Tránsito: motocicleta", "Tránsito: otro vehículo", "Arma de fuego",
         "Arma cortopunzante"], 1))
    return "\n".join([
        "table Mecanismos", "",
        "\tcolumn mecanismo", "\t\tdataType: string", "\t\tsummarizeBy: none", "\t\tsourceColumn: [mecanismo]",
        "\t\tsortByColumn: orden", "",
        "\tcolumn orden", "\t\tdataType: int64", "\t\tformatString: 0", "\t\tisHidden", "\t\tsummarizeBy: none",
        "\t\tsourceColumn: [orden]", "",
        "\tpartition Mecanismos = calculated", "\t\tmode: import",
        f'\t\tsource = DATATABLE("mecanismo", STRING, "orden", INTEGER, {{{filas}}})', ""])


def escribir(ruta, texto):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8", newline="\n")


def escribir_json(ruta, obj):
    escribir(ruta, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def generar_modelo(raiz, admin, control):
    sm = raiz / "Trauma.SemanticModel"
    escribir_json(sm / "definition.pbism", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "settings": {}})
    d = sm / "definition"
    escribir(d / "database.tmdl", "database\n\tcompatibilityLevel: 1567\n")
    tablas = []
    for t, cols in DIMS.items():
        escribir(d / "tables" / f"{t}.tmdl", tmdl_tabla(t, cols))
        tablas.append(t)
    for t, cols in PUENTES_NAVEGADOR.items():
        escribir(d / "tables" / f"{t}.tmdl", tmdl_tabla(t, cols))
        tablas.append(t)
    for t, (sql, cols) in consultas_sql(admin).items():
        escribir(d / "tables" / f"{t}.tmdl", tmdl_tabla(t, cols, sql))
        tablas.append(t)
    medidas = list(MEDIDAS)
    if control:
        for t, (sql, cols) in consultas_control(admin).items():
            escribir(d / "tables" / f"{t}.tmdl", tmdl_tabla(t, cols, sql))
            tablas.append(t)
        medidas += MEDIDAS_CONTROL
    escribir(d / "tables" / "Mecanismos.tmdl", tmdl_mecanismos())
    escribir(d / "tables" / "Medidas.tmdl", tmdl_medidas(medidas))
    tablas += ["Mecanismos", "Medidas"]
    escribir(d / "model.tmdl", "\n".join(
        ["model Model", "\tculture: es-CO", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
         "\tsourceQueryCulture: es-CO", ""] + [f"ref table {t}" for t in tablas]) + "\n")
    escribir(d / "expressions.tmdl", "\n".join([
        'expression Servidor = "localhost:5432" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]', "",
        'expression BaseDatos = "nombre_de_la_base" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]', ""]))
    rel = []
    for i, (desde, hasta, activa, ambos) in enumerate(RELACIONES):
        nombre = hashlib.md5(f"{desde}->{hasta}".encode()).hexdigest()
        lin = [f"relationship {nombre[:8]}-{nombre[8:12]}-{nombre[12:16]}-{nombre[16:20]}-{nombre[20:32]}"]
        if not activa:
            lin.append("\tisActive: false")
        if ambos:
            lin.append("\tcrossFilteringBehavior: bothDirections")
        lin += [f"\tfromColumn: {desde}", f"\ttoColumn: {hasta}", ""]
        rel.append("\n".join(lin))
    escribir(d / "relationships.tmdl", "\n".join(rel))


# ============================================================
# 2. REPORTE (PBIR)
# ============================================================
def lit(v):
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, int):
        return {"expr": {"Literal": {"Value": f"{v}L"}}}
    if isinstance(v, float):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}


SIN_UNIDADES = {"expr": {"Literal": {"Value": "1D"}}}  # unidades de visualizacion: Ninguno


def campo(ref):
    """'Medidas.[Atenciones]' -> medida; 'tabla.columna' -> columna."""
    tabla, prop = ref.split(".", 1)
    if prop.startswith("["):
        return {"Measure": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": prop[1:-1]}}, f"{tabla}.{prop[1:-1]}"
    return {"Column": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": prop}}, f"{tabla}.{prop}"


def M(nombre):
    return f"Medidas.[{nombre}]"


class Pagina:
    def __init__(self, nombre, titulo, alto):
        self.nombre, self.titulo, self.alto = nombre, titulo, alto
        self.visuales = []

    def agregar(self, tipo, x, y, w, h, roles=None, titulo=None, orden=None, objetos=None, sync=None, etiquetas=None):
        nombre = hashlib.md5(f"{self.nombre}-{len(self.visuales)}".encode()).hexdigest()[:20]
        visual = {"visualType": tipo}
        if roles:
            qs = {}
            for rol, refs in roles.items():
                proys = []
                for ref in refs:
                    f, qref = campo(ref)
                    p = {"field": f, "queryRef": qref, "nativeQueryRef": qref.split(".", 1)[1]}
                    if etiquetas and ref in etiquetas:
                        p["displayName"] = etiquetas[ref]
                    proys.append(p)
                qs[rol] = {"projections": proys}
            visual["query"] = {"queryState": qs}
            if orden:
                ref, direccion = orden
                visual["query"]["sortDefinition"] = {
                    "sort": [{"field": campo(ref)[0], "direction": direccion}], "isDefaultSort": False}
        if objetos:
            visual["objects"] = objetos
        vco = {}
        if titulo:
            vco["title"] = [{"properties": {"show": lit(True), "text": lit(titulo)}}]
        elif tipo not in ("textbox",):
            vco["title"] = [{"properties": {"show": lit(False)}}]
        if vco:
            visual["visualContainerObjects"] = vco
        if sync:
            visual["syncGroup"] = {"groupName": sync, "fieldChanges": True, "filterChanges": True}
        visual["drillFilterOtherVisuals"] = True
        self.visuales.append({
            "$schema": f"{SCHEMA_BASE}/visualContainer/2.4.0/schema.json",
            "name": nombre,
            "position": {"x": x, "y": y, "z": len(self.visuales) * 1000, "height": h, "width": w,
                         "tabOrder": len(self.visuales) * 1000},
            "visual": visual})

    # --- atajos ---
    def texto(self, x, y, w, h, t, tam=12, negrita=False, color="#52514e"):
        estilo = {"fontSize": f"{tam}pt", "color": color}
        if negrita:
            estilo["fontWeight"] = "bold"
        self.agregar("textbox", x, y, w, h, objetos={"general": [{"properties": {
            "paragraphs": [{"textRuns": [{"value": t, "textStyle": estilo}]}]}}]})

    def tarjeta(self, x, y, w, h, medida, etiqueta):
        # labelDisplayUnits = 1: numero exacto (sin "mil"/"K"), segun el formato de la medida
        self.agregar("card", x, y, w, h, {"Values": [M(medida)]}, etiquetas={M(medida): etiqueta},
                     objetos={"labels": [{"properties": {"labelDisplayUnits": SIN_UNIDADES}}]})

    def barras(self, x, y, w, h, titulo, categoria, medidas, color=S1, orden_desc=True, tipo="clusteredBarChart",
               etiquetas=None):
        roles = {"Y": [M(m) for m in medidas]}
        if categoria:
            roles = {"Category": [categoria], **roles}
        orden = (M(medidas[0]), "Descending") if (orden_desc and categoria) else (
            (categoria, "Ascending") if categoria else None)
        obj = {"dataPoint": [{"properties": {"fill": {"solid": {"color": lit(color)}}}}],
               "labels": [{"properties": {"show": lit(True), "labelDisplayUnits": SIN_UNIDADES}}]}
        self.agregar(tipo, x, y, w, h, roles, titulo, orden, obj,
                     etiquetas={M(m): e for m, e in (etiquetas or {}).items()})

    def linea(self, x, y, w, h, titulo, categoria, medida, color=S1):
        obj = {"dataPoint": [{"properties": {"fill": {"solid": {"color": lit(color)}}}}]}
        self.agregar("lineChart", x, y, w, h, {"Category": [categoria], "Y": [M(medida)]}, titulo,
                     (categoria, "Ascending"), obj)

    def tabla(self, x, y, w, h, titulo, refs, orden=None, etiquetas=None):
        self.agregar("tableEx", x, y, w, h, {"Values": refs}, titulo, orden, etiquetas=etiquetas)

    def segmentador(self, x, y, w, h, ref, etiqueta, sync):
        self.agregar("slicer", x, y, w, h, {"Values": [ref]}, objetos={
            "data": [{"properties": {"mode": lit("Dropdown")}}]}, sync=sync, etiquetas={ref: etiqueta})


SEGMENTADORES = [("dim_tiempo.anio", "Año"), ("dim_tiempo.nombre_mes", "Mes"), ("dim_tiempo.tipo_dia", "Tipo de día"),
                 ("dim_tiempo.es_festivo", "Festivo"), ("dim_paciente.genero", "Género"),
                 ("dim_paciente.quinquenio", "Quinquenio"),
                 ("dim_mecanismo_primario.mecanismo_primario", "Mecanismo"), ("fact_trauma.rango_iss", "Rango ISS"),
                 ("dim_paciente.tipo_seguro", "Seguro")]


def encabezado(p, con_filtros=True):
    p.texto(16, 8, 440, 40, f"Trauma HUV · {p.titulo}", 16, True, "#0b0b0b")
    if not con_filtros:
        return
    p.segmentador(800, 4, 220, 52, "dim_armas.con_arma_fuego", "Arma de fuego", "rapido_fuego")
    p.segmentador(1040, 4, 220, 52, "dim_armas.con_arma_cortopunzante", "Arma cortopunzante", "rapido_corto")
    ancho, hueco = 128, 11
    for i, (ref, et) in enumerate(SEGMENTADORES):
        p.segmentador(20 + i * (ancho + hueco), 58, ancho, 50, ref, et, "g_" + ref.split(".")[1])


def pagina_demografia():
    p = Pagina("p1_demografia", "Demografía", 720)
    encabezado(p)
    ancho = (1240 - 4 * 10) / 5
    for i, (m, e) in enumerate([("Atenciones", "Atenciones"), ("% hombres", "Hombres"), ("% mujeres", "Mujeres"),
                                ("Quinquenio más frecuente", "Quinquenio más frecuente"),
                                ("Promedio diario", "Promedio diario")]):
        p.tarjeta(round(20 + i * (ancho + 10)), 116, round(ancho), 72, m, e)
    p.agregar("barChart", 20, 196, 620, 504,
              {"Category": ["dim_paciente.quinquenio"], "Series": ["dim_paciente.genero"], "Y": [M("Pirámide")]},
              "Pirámide poblacional (% de las atenciones)", ("dim_paciente.quinquenio", "Descending"),
              {"labels": [{"properties": {"show": lit(True)}}]})
    p.barras(650, 196, 610, 160, "Atenciones por tipo de seguro", "dim_paciente.tipo_seguro", ["Atenciones"])
    p.barras(650, 366, 610, 160, "Atenciones por estado civil", "dim_paciente.estado_civil", ["Atenciones"])
    p.barras(650, 536, 610, 164, "Atenciones por nacionalidad", "dim_paciente.nacionalidad", ["Atenciones"])
    return p


def pagina_atencion():
    p = Pagina("p2_atencion", "Atención", 750)
    encabezado(p)
    kpis = [("Atenciones", "Atenciones"), ("ISS promedio", "ISS promedio"), ("% ISS ≥ 16", "ISS ≥ 16"),
            ("% GCS < 9", "GCS < 9"), ("% PAS < 90", "PAS < 90"), ("% índice de choque > 0,9", "Choque > 0,9"),
            ("Mortalidad", "Mortalidad"), ("% con UCI", "Con UCI"), ("% con procedimiento", "Con procedimiento"),
            ("% con imagen", "Con imagen"), ("% transfundidos", "Transfundidos")]
    ancho = (1240 - 10 * 8) / 11
    for i, (m, e) in enumerate(kpis):
        p.tarjeta(round(20 + i * (ancho + 8)), 116, round(ancho), 66, m, e)
    p.texto(16, 188, 300, 24, "TIPO DE TRAUMA", 9, True, "#7a7974")
    p.linea(20, 212, 520, 250, "Atenciones por mes (fecha de admisión)", "dim_tiempo.anio_mes", "Atenciones")
    p.barras(550, 212, 390, 250, "Atenciones por mecanismo", "Mecanismos.mecanismo", ["Atenciones por mecanismo"])
    p.barras(950, 212, 310, 250, "Contexto del evento (% de atenciones)", None,
             ["% violencia", "% consumo de alcohol", "% con sustancia", "% autolesión"],
             etiquetas={"% violencia": "Violencia", "% consumo de alcohol": "Alcohol",
                        "% con sustancia": "Sustancias", "% autolesión": "Autolesión"})
    p.texto(16, 470, 300, 24, "DEMANDA", 9, True, "#7a7974")
    p.barras(20, 494, 520, 240, "Atenciones por día de la semana", "dim_tiempo.dia_semana", ["Atenciones"],
             orden_desc=False, tipo="clusteredColumnChart")
    p.barras(550, 494, 390, 240, "Promedio diario por tipo de día", "dim_tiempo.tipo_dia", ["Promedio diario"])
    p.agregar("multiRowCard", 950, 494, 310, 240,
              {"Values": [M("Promedio diario"), M("Cobertura del mecanismo primario"), M("Cobertura arma de fuego"),
                          M("Cobertura arma cortopunzante"), M("Cobertura consumo de alcohol")]},
              "Promedio diario y cobertura de los filtros")
    return p


def pagina_severidad():
    p = Pagina("p3_severidad", "Severidad y resultado", 940)
    encabezado(p)
    p.texto(16, 112, 300, 22, "SEVERIDAD", 9, True, "#7a7974")
    p.barras(20, 134, 300, 250, "Atenciones por rango de ISS", "fact_trauma.rango_iss", ["Atenciones"],
             orden_desc=False, tipo="clusteredColumnChart")
    ais = ["AIS cabeza", "AIS cara", "AIS tórax", "AIS abdomen", "AIS extremidades", "AIS externo"]
    p.barras(330, 134, 300, 250, "AIS promedio por región", None, ais,
             etiquetas={m: m.replace("AIS ", "").capitalize() for m in ais})
    p.agregar("multiRowCard", 640, 134, 620, 250,
              {"Values": [M(m) for m in ["PAS promedio", "PAD promedio", "FC promedio", "FR promedio",
                                         "Saturación promedio", "Temperatura promedio", "GCS promedio"]]},
              "Signos vitales: promedio de la primera toma")
    p.texto(16, 392, 300, 22, "RESULTADO", 9, True, "#7a7974")
    p.barras(20, 414, 300, 240, "Destino del paciente", "dim_desenlace.grupo_destino", ["Atenciones"])
    p.barras(330, 414, 300, 240, "Mortalidad por rango de ISS", "fact_trauma.rango_iss", ["Mortalidad"], S2,
             orden_desc=False, tipo="clusteredColumnChart")
    p.barras(640, 414, 310, 240, "Mortalidad por mecanismo", "Mecanismos.mecanismo", ["Mortalidad por mecanismo"], S2)
    p.barras(960, 414, 300, 240, "Muertes según prevenibilidad", "dim_desenlace.muerte_prevenible", ["Fallecidos"])
    p.texto(16, 662, 300, 22, "RECURSOS Y ESTANCIA", 9, True, "#7a7974")
    p.barras(20, 684, 290, 240, "Procedimientos más frecuentes", "dim_procedimiento.procedimientos",
             ["Atenciones con procedimiento"])
    p.barras(320, 684, 290, 240, "Imágenes por tipo", "dim_imagen.tipo_imagen", ["Atenciones con imagen"])
    p.linea(620, 684, 340, 240, "Sangre transfundida por mes (litros)", "dim_tiempo.anio_mes", "Litros de sangre")
    p.barras(970, 684, 290, 240, "Estancia: días promedio", None,
             ["Estancia admisión–alta (promedio)", "Días de hospitalización (promedio)", "Días de UCI (promedio)"],
             etiquetas={"Estancia admisión–alta (promedio)": "Admisión–alta",
                        "Días de hospitalización (promedio)": "Hospitalización",
                        "Días de UCI (promedio)": "UCI"})
    return p


def pagina_diagnosticos(admin):
    p = Pagina("p4_diagnosticos", "Diagnósticos y lesiones", 830)
    encabezado(p)
    p.barras(20, 116, 540, 400, "Diagnósticos CIE-10 más frecuentes", "dim_cie_10.cie_10",
             ["Atenciones con diagnóstico"])
    p.barras(570, 116, 340, 194, "Comorbilidades más frecuentes", "dim_cie_10.cie_10", ["Atenciones con comorbilidad"])
    p.barras(570, 322, 340, 194, "Complicaciones más frecuentes", "dim_cie_10.cie_10", ["Atenciones con complicación"])
    p.barras(920, 116, 340, 400, "Lesiones por parte del cuerpo", "dim_parte_cuerpo_lesion.parte_cuerpo",
             ["Atenciones con lesión"])
    refs = ["fact_trauma.fact_id"] + (["fact_trauma.motivo_consulta"] if admin else []) + [
        "dim_cie_10.cie_10", M("Atenciones con diagnóstico")]
    p.tabla(20, 528, 1240, 290, "Detalle por atención (una fila por diagnóstico)", refs,
            ("fact_trauma.fact_id", "Ascending"),
            etiquetas={"dim_cie_10.cie_10": "diagnóstico", M("Atenciones con diagnóstico"): "n"})
    return p


def pagina_cargas():
    p = Pagina("p5_cargas", "Cargas de la bodega", 660)
    encabezado(p, con_filtros=False)
    p.texto(16, 56, 1240, 30, "Esta página no responde a los segmentadores: muestra el control del ETL "
                              "(solo conteos del modelo completo).", 10)
    ancho = (1240 - 4 * 10) / 5
    for i, (m, e) in enumerate([("Última carga exitosa", "Última carga exitosa"),
                                ("Último veredicto", "Veredicto de calidad"),
                                ("Reglas que cumplen (última)", "Reglas que cumplen"),
                                ("Reglas que advierten (última)", "Reglas que advierten"),
                                ("Reglas que fallan (última)", "Reglas que fallan")]):
        p.tarjeta(round(20 + i * (ancho + 10)), 96, round(ancho), 80, m, e)
    p.tabla(20, 188, 1240, 230, "Reconciliación por carga (origen = cargadas + no usadas + cuarentena)",
            ["carga.ejecutado_en", "carga.modelo", "carga.fuente", "carga.filas_origen", "carga.filas_cargadas",
             "carga.filas_no_usadas", "carga.filas_cuarentena", "carga.exitosa"], ("carga.ejecutado_en", "Descending"))
    p.tabla(20, 428, 1240, 220, "Atenciones por carga (carga incremental)",
            ["carga.ejecutado_en", "carga.modelo", "carga.fuente", "carga.atenciones_nuevas",
             "carga.atenciones_modificadas", "carga.atenciones_sin_cambio", "carga.atenciones_eliminadas"],
            ("carga.ejecutado_en", "Descending"))
    return p


def pagina_textos():
    """Solo variante admin: el texto libre que el lector no puede ver."""
    p = Pagina("p6_textos", "Textos libres (administración)", 900)
    encabezado(p)
    p.tabla(20, 116, 1240, 250, "Atención: motivo, otras sustancias y detalles de hospitalización",
            ["fact_trauma.fact_id", "fact_trauma.trauma_register_id", "fact_trauma.motivo_consulta",
             "fact_trauma.otras_sustancias_de_abuso", "fact_trauma.detalles_hospitalizacion"],
            ("fact_trauma.fact_id", "Ascending"))
    p.tabla(20, 376, 1240, 250, "Imágenes: descripción", [
        "bridge_atencion_imagen.fact_id", "bridge_atencion_imagen.secuencia", "dim_imagen.tipo_imagen",
        "dim_imagen.parte_cuerpo", "bridge_atencion_imagen.descripcion_imagen"],
            ("bridge_atencion_imagen.fact_id", "Ascending"))
    p.tabla(20, 636, 615, 250, "CIE-10 sin código: texto de origen", [
        "bridge_atencion_cie_10.fact_id", "bridge_atencion_cie_10.rol", "dim_cie_10.cie_10",
        "bridge_atencion_cie_10.texto_origen"], ("bridge_atencion_cie_10.fact_id", "Ascending"))
    p.tabla(645, 636, 615, 250, "Complicaciones: texto de origen", [
        "bridge_atencion_complicacion.fact_id", "dim_cie_10.cie_10", "bridge_atencion_complicacion.lugar_complicacion",
        "bridge_atencion_complicacion.texto_origen"], ("bridge_atencion_complicacion.fact_id", "Ascending"))
    return p


def generar_reporte(raiz, admin, control):
    rp = raiz / "Trauma.Report"
    escribir_json(rp / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": "../Trauma.SemanticModel"}}})
    d = rp / "definition"
    escribir_json(d / "version.json", {"$schema": f"{SCHEMA_BASE}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    escribir_json(d / "report.json", {"$schema": f"{SCHEMA_BASE}/report/3.0.0/schema.json", "themeCollection": {}})
    paginas = [pagina_demografia(), pagina_atencion(), pagina_severidad(), pagina_diagnosticos(admin)]
    if control:
        paginas.append(pagina_cargas())
    if admin:
        paginas.append(pagina_textos())
    escribir_json(d / "pages" / "pages.json", {"$schema": f"{SCHEMA_BASE}/pagesMetadata/1.0.0/schema.json",
                                               "pageOrder": [p.nombre for p in paginas],
                                               "activePageName": paginas[0].nombre})
    for p in paginas:
        pd = d / "pages" / p.nombre
        escribir_json(pd / "page.json", {"$schema": f"{SCHEMA_BASE}/page/2.0.0/schema.json", "name": p.nombre,
                                         "displayName": p.titulo, "displayOption": "FitToWidth",
                                         "height": p.alto, "width": 1280})
        for v in p.visuales:
            escribir_json(pd / "visuals" / v["name"] / "visual.json", v)
    return paginas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("salida", type=Path)
    ap.add_argument("--variante", choices=["estandar", "admin"], default="estandar")
    ap.add_argument("--sin-control", action="store_true")
    a = ap.parse_args()
    repo = Path(__file__).resolve().parents[3]
    raiz = a.salida.resolve()
    if repo in raiz.parents or raiz == repo:
        raise SystemExit("La salida debe quedar FUERA del repositorio: el proyecto guardara datos al actualizarse.")
    admin, control = a.variante == "admin", not a.sin_control
    raiz.mkdir(parents=True, exist_ok=True)
    generar_modelo(raiz, admin, control)
    paginas = generar_reporte(raiz, admin, control)
    escribir_json(raiz / "Trauma.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": "Trauma.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    print(f"Proyecto generado en {raiz} (variante {a.variante}, {len(paginas)} paginas, "
          f"{sum(len(p.visuales) for p in paginas)} visuales)")


if __name__ == "__main__":
    main()
