-- ============================================================
-- Conteos de dominios para definir las medidas del reporte de Power BI
-- Se ejecuta con el rol lector (DB_READER_USER) y el resultado se guarda como CSV.
-- Devuelve SOLO frecuencias por categoria (campo, valor, n): ninguna fila de
-- paciente ni identificador. Si alguna categoria tiene muy pocos casos y se
-- considera identificable, se puede reemplazar su n por '<5' antes de compartir.
-- Usa solo columnas permitidas al lector (ver 04_permissions.sql).
-- ============================================================

-- Destino y muerte prevenible, por atencion
SELECT 'disposicion_paciente' AS campo, COALESCE(d.disposicion_paciente, '(nulo)') AS valor, COUNT(*) AS n
FROM trauma_completo.fact_trauma f
LEFT JOIN trauma_completo.dim_desenlace d ON d.desenlace_id = f.desenlace_id
GROUP BY 2
UNION ALL
SELECT 'muerte_prevenible', COALESCE(d.muerte_prevenible, '(nulo)'), COUNT(*)
FROM trauma_completo.fact_trauma f
LEFT JOIN trauma_completo.dim_desenlace d ON d.desenlace_id = f.desenlace_id
GROUP BY 2
UNION ALL
-- Mecanismo de transito y contexto del evento
SELECT 'tipo_vehiculo', COALESCE(a.tipo_vehiculo, '(nulo)'), COUNT(*)
FROM trauma_completo.fact_trauma f
LEFT JOIN trauma_completo.dim_accidente_transito a ON a.accidente_id = f.accidente_id
GROUP BY 2
UNION ALL
SELECT 'ocupante', COALESCE(a.ocupante, '(nulo)'), COUNT(*)
FROM trauma_completo.fact_trauma f
LEFT JOIN trauma_completo.dim_accidente_transito a ON a.accidente_id = f.accidente_id
GROUP BY 2
UNION ALL
SELECT 'violencia', COALESCE(e.violencia, '(nulo)'), COUNT(*)
FROM trauma_completo.fact_trauma f
LEFT JOIN trauma_completo.dim_evento_trauma e ON e.evento_id = f.evento_id
GROUP BY 2
UNION ALL
-- Mecanismo primario por atencion (atenciones distintas, no filas del puente)
SELECT 'mecanismo_primario', COALESCE(m.mecanismo_primario, '(nulo)'), COUNT(DISTINCT b.fact_id)
FROM trauma_completo.bridge_atencion_lesion b
LEFT JOIN trauma_completo.dim_mecanismo_primario m ON m.mecanismo_primario_id = b.mecanismo_primario_id
GROUP BY 2
UNION ALL
-- Significado del nulo y del cero en las medidas
SELECT 'uci_dias', CASE WHEN uci_dias IS NULL THEN '(nulo)' WHEN uci_dias = 0 THEN '0' ELSE '> 0' END, COUNT(*)
FROM trauma_completo.fact_trauma
GROUP BY 2
UNION ALL
SELECT 'sangre_l', CASE WHEN sangre_l IS NULL THEN '(nulo)' WHEN sangre_l = 0 THEN '0' ELSE '> 0' END, COUNT(*)
FROM trauma_completo.fact_trauma
GROUP BY 2
UNION ALL
SELECT 'iss', CASE WHEN iss IS NULL THEN '(nulo)' ELSE 'con dato' END, COUNT(*)
FROM trauma_completo.fact_trauma
GROUP BY 2
UNION ALL
SELECT 'gcs_completo',
       CASE WHEN gcs_ocular IS NULL OR gcs_verbal IS NULL OR gcs_motor IS NULL THEN 'incompleto' ELSE 'completo' END,
       COUNT(*)
FROM trauma_completo.fact_trauma
GROUP BY 2
UNION ALL
SELECT 'presion_sistolica',
       CASE WHEN presion_sistolica IS NULL THEN '(nulo)' WHEN presion_sistolica = 0 THEN '0' ELSE '> 0' END,
       COUNT(*)
FROM trauma_completo.fact_trauma
GROUP BY 2
UNION ALL
-- Fechas para la estancia (admision a alta)
SELECT 'admision_a_alta',
       CASE WHEN ta.fecha IS NULL OR tl.fecha IS NULL THEN 'falta una fecha'
            WHEN tl.fecha < ta.fecha THEN 'alta antes de admision'
            ELSE 'fechas validas' END,
       COUNT(*)
FROM trauma_completo.fact_trauma f
LEFT JOIN trauma_completo.dim_tiempo ta ON ta.tiempo_id = f.fecha_admision_id
LEFT JOIN trauma_completo.dim_tiempo tl ON tl.tiempo_id = f.fecha_alta_id
GROUP BY 2
ORDER BY 1, 3 DESC;
