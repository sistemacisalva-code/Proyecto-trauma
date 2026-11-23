-- ============================================================
-- INDICES DEL MODELO COMPLETO (esquema trauma_completo)
-- PostgreSQL no indexa automaticamente las columnas FK.
-- Las PK y los UNIQUE ya generan su propio indice.
-- ============================================================

-- FK de la tabla de hechos
CREATE INDEX IF NOT EXISTS ix_fact_fecha_hospitalizacion ON trauma_completo.fact_trauma (fecha_hospitalizacion_id);
CREATE INDEX IF NOT EXISTS ix_fact_fecha_alta            ON trauma_completo.fact_trauma (fecha_alta_id);
CREATE INDEX IF NOT EXISTS ix_fact_fecha_admision        ON trauma_completo.fact_trauma (fecha_admision_id);
CREATE INDEX IF NOT EXISTS ix_fact_hora_alta             ON trauma_completo.fact_trauma (hora_alta_id);
CREATE INDEX IF NOT EXISTS ix_fact_paciente              ON trauma_completo.fact_trauma (paciente_id);
CREATE INDEX IF NOT EXISTS ix_fact_evento                ON trauma_completo.fact_trauma (evento_id);
CREATE INDEX IF NOT EXISTS ix_fact_caida                 ON trauma_completo.fact_trauma (caida_id);
CREATE INDEX IF NOT EXISTS ix_fact_quemadura             ON trauma_completo.fact_trauma (quemadura_id);
CREATE INDEX IF NOT EXISTS ix_fact_accidente             ON trauma_completo.fact_trauma (accidente_id);
CREATE INDEX IF NOT EXISTS ix_fact_armas                 ON trauma_completo.fact_trauma (armas_id);
CREATE INDEX IF NOT EXISTS ix_fact_desenlace             ON trauma_completo.fact_trauma (desenlace_id);
CREATE INDEX IF NOT EXISTS ix_fact_calificador_signos    ON trauma_completo.fact_trauma (calificador_signos_id);

-- Puentes (fact_id ya queda cubierto por el prefijo de la PK compuesta o, en bridge_atencion_cie_10 y
-- bridge_atencion_complicacion, de su UNIQUE)
CREATE INDEX IF NOT EXISTS ix_brg_lesion_parte   ON trauma_completo.bridge_atencion_lesion (parte_cuerpo_lesion_id);
CREATE INDEX IF NOT EXISTS ix_brg_lesion_mecan   ON trauma_completo.bridge_atencion_lesion (mecanismo_primario_id);
CREATE INDEX IF NOT EXISTS ix_brg_lesion_tipo    ON trauma_completo.bridge_atencion_lesion (tipo_lesion_id);
CREATE INDEX IF NOT EXISTS ix_brg_imagen_imagen  ON trauma_completo.bridge_atencion_imagen (imagen_id);
CREATE INDEX IF NOT EXISTS ix_brg_cie_10         ON trauma_completo.bridge_atencion_cie_10 (cie_10_id);
CREATE INDEX IF NOT EXISTS ix_brg_complicacion   ON trauma_completo.bridge_atencion_complicacion (cie_10_id);
CREATE INDEX IF NOT EXISTS ix_brg_sustancia      ON trauma_completo.bridge_atencion_sustancia (sustancia_id);
CREATE INDEX IF NOT EXISTS ix_brg_proced_proc    ON trauma_completo.bridge_atencion_procedimiento (procedimiento_id);
CREATE INDEX IF NOT EXISTS ix_brg_proced_fecha   ON trauma_completo.bridge_atencion_procedimiento (fecha_inicio_id);
CREATE INDEX IF NOT EXISTS ix_brg_proced_hora    ON trauma_completo.bridge_atencion_procedimiento (hora_inicio_id);
