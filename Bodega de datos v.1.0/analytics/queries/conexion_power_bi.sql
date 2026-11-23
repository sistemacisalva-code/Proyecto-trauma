-- ============================================================
-- Consultas de conexion de Power BI a trauma_completo (rol lector)
-- Uso: Obtener datos > Base de datos PostgreSQL > Opciones avanzadas >
--      "Instruccion SQL", una consulta por tabla. Modo: Importar.
--      Nombre de cada consulta en Power BI: el de la tabla, sin el esquema.
--
-- Por que existen: el lector tiene SELECT por columna y no puede leer
-- las columnas excluidas en database/schema/04_permissions.sql. El
-- navegador de Power BI pide todas las columnas y falla en estas tablas.
-- Aqui se listan solo las columnas permitidas, y de fact_trauma solo las
-- que usa el reporte (sin texto libre ni la llave de negocio).
--
-- Las demas tablas (dim_* y los puentes de lesion, procedimiento y
-- sustancia) no tienen columnas excluidas: se cargan desde el navegador.
-- Si 04_permissions.sql cambia la lista de exclusion, revisar este archivo.
-- ============================================================

-- 1. fact_trauma  (excluidas: detalles_hospitalizacion, huella)
SELECT
    fact_id,
    fecha_admision_id, fecha_hospitalizacion_id, fecha_alta_id, hora_alta_id,
    paciente_id, evento_id, caida_id, quemadura_id, accidente_id, armas_id,
    desenlace_id, calificador_signos_id,
    gcs_ocular, gcs_verbal, gcs_motor,
    presion_sistolica, presion_diastolica, frecuencia_cardiaca,
    frecuencia_respiratoria, saturacion_o2, temperatura_c,
    iss, cabeza, cara, torax, abdomen, extremidades, externo,
    dias_hospitalizacion, uci_dias, sangre_l
FROM trauma_completo.fact_trauma;

-- 2. bridge_atencion_imagen  (excluida: descripcion_imagen)
SELECT fact_id, secuencia, imagen_id
FROM trauma_completo.bridge_atencion_imagen;

-- 3. bridge_atencion_cie_10  (excluida: texto_origen)
SELECT atencion_cie_10_id, fact_id, cie_10_id, rol
FROM trauma_completo.bridge_atencion_cie_10;

-- 4. bridge_atencion_complicacion  (excluida: texto_origen)
SELECT complicacion_id, fact_id, cie_10_id, lugar_complicacion
FROM trauma_completo.bridge_atencion_complicacion;

-- 5. Pagina "Cargas de la bodega". Solo funcionan cuando el rol lector tenga SELECT sobre
--    etl_control.carga y etl_control.calidad (cambio de 04_permissions.sql aun no aplicado).
--    Nombre de las consultas en Power BI: carga y calidad.

-- 5a. etl_control.carga  (excluidas: run_id_staging, ruta_cuarentena)
SELECT id, modelo, fuente, filas_origen, filas_cargadas, filas_no_usadas, filas_cuarentena,
       atenciones_nuevas, atenciones_modificadas, atenciones_sin_cambio, atenciones_eliminadas,
       exitosa, ejecutado_en
FROM etl_control.carga;

-- 5b. etl_control.calidad  (excluida: ruta_reporte)
SELECT id, modelo, veredicto, reglas_cumplen, reglas_advierten, reglas_fallan, ejecutado_en
FROM etl_control.calidad;
