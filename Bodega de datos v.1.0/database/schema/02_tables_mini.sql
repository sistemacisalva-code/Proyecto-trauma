-- ============================================================
-- MODELO MINI (alternativo): esquema trauma_mini
-- Idempotente: se puede re-ejecutar sin errores.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS trauma_mini;

CREATE TABLE IF NOT EXISTS trauma_mini.dwh_dim_calendario (
    id_fecha        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha           DATE NOT NULL UNIQUE,
    anio            INTEGER,
    dayofweeknumber INTEGER,
    dia_semana      TEXT,
    diames          INTEGER,
    es_festivo      TEXT
);

-- Una fila por minuto del dia (1 440). 
CREATE TABLE IF NOT EXISTS trauma_mini.dwh_dim_horario (
    id_horario INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hora_larga TEXT    NOT NULL,                                  -- '12:00:00 a. m.'
    hora       INTEGER NOT NULL CHECK (hora BETWEEN 0 AND 23),
    minuto     INTEGER NOT NULL CHECK (minuto BETWEEN 0 AND 59),
    intervalo  TEXT    NOT NULL,                                  -- '00:00 - 01:00'
    CONSTRAINT uq_dwh_dim_horario UNIQUE (hora, minuto)
);

CREATE TABLE IF NOT EXISTS trauma_mini.dwh_dim_municipio (
    id     INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS trauma_mini.dwh_dim_perfildem (
    key_perfil_dem INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    estado_civil   TEXT,
    genero         TEXT,
    ocupacion      TEXT,
    quinquenio     TEXT,
    CONSTRAINT uq_dwh_dim_perfildem UNIQUE NULLS NOT DISTINCT (estado_civil, genero, ocupacion, quinquenio)
);

CREATE TABLE IF NOT EXISTS trauma_mini.dwh_dim_trauma (
    key_tipotrauma             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo_trauma                TEXT,
    tipo_subtrauma             TEXT,
    descripcion_tipo_trauma    TEXT,
    descripcion_tipo_subtrauma TEXT,
    CONSTRAINT uq_dwh_dim_trauma UNIQUE NULLS NOT DISTINCT (tipo_trauma, tipo_subtrauma)
);

-- Las medidas (Porcentaje_del_Total_de_Casos, PromedioHorasEstancia,
-- PromedioTiempoMedico, PromedioTiempoUrgenciasH) NO se materializan: son DAX.
CREATE TABLE IF NOT EXISTS trauma_mini.dwh_dim_hechos (
    id                                    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trauma_register_record_id             TEXT NOT NULL UNIQUE,
    key_perfil_dem                        INTEGER REFERENCES trauma_mini.dwh_dim_perfildem (key_perfil_dem),
    key_tipotrauma                        INTEGER REFERENCES trauma_mini.dwh_dim_trauma (key_tipotrauma),
    municipio                             INTEGER REFERENCES trauma_mini.dwh_dim_municipio (id),
    id_fecha_de_alta                      INTEGER REFERENCES trauma_mini.dwh_dim_calendario (id_fecha),
    id_fecha_de_la_disposicion            INTEGER REFERENCES trauma_mini.dwh_dim_calendario (id_fecha),
    id_fecha_de_llegada_del_medico        INTEGER REFERENCES trauma_mini.dwh_dim_calendario (id_fecha),
    id_fecha_de_llegada_del_paciente      INTEGER REFERENCES trauma_mini.dwh_dim_calendario (id_fecha),
    id_horario_de_alta                    INTEGER REFERENCES trauma_mini.dwh_dim_horario (id_horario),
    id_horario_de_la_disposicion          INTEGER REFERENCES trauma_mini.dwh_dim_horario (id_horario),
    id_horario_de_llegada_del_medico      INTEGER REFERENCES trauma_mini.dwh_dim_horario (id_horario),
    id_horario_de_llegada_del_paciente    INTEGER REFERENCES trauma_mini.dwh_dim_horario (id_horario),
    descripcion_del_diagnostico           TEXT,
    motivo_de_consulta                    TEXT,
    muerte_prevenible                     TEXT,
    muerte_prevenible_del_hospitalizado   TEXT,
    tiempo_en_sala_de_emergencias_horas   NUMERIC,
    tiempo_en_sala_de_emergencias_minutos NUMERIC
);

-- Copo de nieve: una fila por subtipo de trauma ocurrido en un registro.
-- Va despues del hecho porque referencia su clave de negocio.
CREATE TABLE IF NOT EXISTS trauma_mini.dwh_dim_subdimtrauma (
    key_tiposubdimtrauma       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trauma_register_record_id  TEXT    NOT NULL REFERENCES trauma_mini.dwh_dim_hechos (trauma_register_record_id) ON DELETE CASCADE,
    key_tipotrauma             INTEGER NOT NULL REFERENCES trauma_mini.dwh_dim_trauma (key_tipotrauma),
    descripcion_tipo_subtrauma TEXT,
    CONSTRAINT uq_subdim_registro_trauma UNIQUE (trauma_register_record_id, key_tipotrauma)
);
