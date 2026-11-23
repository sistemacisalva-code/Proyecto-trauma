-- ============================================================
-- Consultas de conexion de Power BI: VERSION DE ADMINISTRACION
-- Todas las columnas del tablero, incluido el texto libre que el rol
-- lector no puede ver (database/schema/04_permissions.sql).
--
-- Uso: solo en la copia del reporte para usuarios autorizados, con un rol
-- que tenga SELECT sobre todas las columnas (ver la seccion "Copia
-- restringida" de docs/tecnico/06_tablero_power_bi.md).
-- Esa copia contiene texto clinico libre: se guarda fuera del repositorio
-- y no se comparte con usuarios del reporte estandar.
--
-- Mismo nombre de consulta que en conexion_power_bi.sql, asi las relaciones
-- y las medidas DAX sirven sin cambios. Se omite solo fact_trauma.huella
-- (dato tecnico de la carga incremental, sin uso analitico).
-- ============================================================

-- 1. fact_trauma
SELECT
    fact_id, trauma_register_id,
    fecha_admision_id, fecha_hospitalizacion_id, fecha_alta_id, hora_alta_id,
    paciente_id, evento_id, caida_id, quemadura_id, accidente_id, armas_id,
    desenlace_id, calificador_signos_id,
    peso, altura, altura_metros, scq,
    gcs_ocular, gcs_verbal, gcs_motor, duracion_perdida_conciencia,
    presion_sistolica, presion_diastolica, frecuencia_cardiaca,
    frecuencia_respiratoria, saturacion_o2, temperatura_c, pao2, paco2,
    iss, cabeza, cara, torax, abdomen, extremidades, externo,
    dias_hospitalizacion, uci_dias, sangre_l,
    motivo_consulta, otras_sustancias_de_abuso, detalles_hospitalizacion
FROM trauma_completo.fact_trauma;

-- 2. bridge_atencion_imagen
SELECT fact_id, secuencia, imagen_id, descripcion_imagen
FROM trauma_completo.bridge_atencion_imagen;

-- 3. bridge_atencion_cie_10
SELECT atencion_cie_10_id, fact_id, cie_10_id, rol, texto_origen
FROM trauma_completo.bridge_atencion_cie_10;

-- 4. bridge_atencion_complicacion
SELECT complicacion_id, fact_id, cie_10_id, lugar_complicacion, texto_origen
FROM trauma_completo.bridge_atencion_complicacion;

-- 5a. etl_control.carga
SELECT id, modelo, fuente, run_id_staging, filas_origen, filas_cargadas, filas_no_usadas,
       filas_cuarentena, atenciones_nuevas, atenciones_modificadas, atenciones_sin_cambio,
       atenciones_eliminadas, ruta_cuarentena, exitosa, ejecutado_en
FROM etl_control.carga;

-- 5b. etl_control.calidad
SELECT id, modelo, veredicto, reglas_cumplen, reglas_advierten, reglas_fallan, ruta_reporte, ejecutado_en
FROM etl_control.calidad;
