-- ============================================================
-- INDICES DEL MODELO MINI (esquema trauma_mini)
-- PostgreSQL no indexa automaticamente las columnas FK.
-- Las PK y los UNIQUE ya generan su propio indice.
-- ============================================================

CREATE INDEX IF NOT EXISTS ix_hechos_perfil     ON trauma_mini.dwh_dim_hechos (key_perfil_dem);
CREATE INDEX IF NOT EXISTS ix_hechos_trauma     ON trauma_mini.dwh_dim_hechos (key_tipotrauma);
CREATE INDEX IF NOT EXISTS ix_hechos_municipio  ON trauma_mini.dwh_dim_hechos (municipio);
CREATE INDEX IF NOT EXISTS ix_hechos_f_alta     ON trauma_mini.dwh_dim_hechos (id_fecha_de_alta);
CREATE INDEX IF NOT EXISTS ix_hechos_f_disp     ON trauma_mini.dwh_dim_hechos (id_fecha_de_la_disposicion);
CREATE INDEX IF NOT EXISTS ix_hechos_f_medico   ON trauma_mini.dwh_dim_hechos (id_fecha_de_llegada_del_medico);
CREATE INDEX IF NOT EXISTS ix_hechos_f_paciente ON trauma_mini.dwh_dim_hechos (id_fecha_de_llegada_del_paciente);
CREATE INDEX IF NOT EXISTS ix_hechos_h_alta     ON trauma_mini.dwh_dim_hechos (id_horario_de_alta);
CREATE INDEX IF NOT EXISTS ix_hechos_h_disp     ON trauma_mini.dwh_dim_hechos (id_horario_de_la_disposicion);
CREATE INDEX IF NOT EXISTS ix_hechos_h_medico   ON trauma_mini.dwh_dim_hechos (id_horario_de_llegada_del_medico);
CREATE INDEX IF NOT EXISTS ix_hechos_h_paciente ON trauma_mini.dwh_dim_hechos (id_horario_de_llegada_del_paciente);
-- El UNIQUE (trauma_register_record_id, key_tipotrauma) ya cubre el registro como prefijo.
CREATE INDEX IF NOT EXISTS ix_subdim_trauma     ON trauma_mini.dwh_dim_subdimtrauma (key_tipotrauma);
