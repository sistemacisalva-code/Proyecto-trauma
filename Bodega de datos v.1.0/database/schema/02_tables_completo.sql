-- ============================================================
-- MODELO COMPLETO (trabajo de grado): esquema trauma_completo
-- Version anterior (rollback): database/archivados/2026-10-26_completo_v1/
-- Idempotente: se puede re-ejecutar sin errores.
--
-- Reglas de modelado (Kimball):
--   * Grano del hecho: una fila por atencion. Lo multivalor va en tablas puente.
--   * El hecho guarda claves, medidas y solo texto libre degenerado.
--   * Una dimension por pregunta analitica, con atributos que se registran juntos.
--   * Sin nulos descriptivos: la carga escribe 'Sin dato' (atributo vacio) o apunta a la
--     combinacion 'No aplica' (grupo vacio). Las medidas y las fechas sin dato quedan en NULL.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS trauma_completo;

-- ===== DIMENSIONES =====
-- Quien es? Perfil demografico (no identifica a la persona)
CREATE TABLE IF NOT EXISTS trauma_completo.dim_paciente (
    paciente_id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quinquenio         TEXT,       -- etiqueta, p. ej. '30-34' (igual que el mini)
    quinquenio_orden   INTEGER,    -- 1 a 18, para ordenar la etiqueta en Power BI
    estado_civil       TEXT,
    genero             TEXT,
    nacionalidad       TEXT,
    tipo_seguro        TEXT,
    paciente_asegurado TEXT,
    CONSTRAINT uq_dim_paciente UNIQUE NULLS NOT DISTINCT (
        quinquenio, estado_civil, genero, nacionalidad, tipo_seguro, paciente_asegurado)
);

-- En que contexto? El abuso de sustancias es multivalor: va en bridge_atencion_sustancia.
CREATE TABLE IF NOT EXISTS trauma_completo.dim_evento_trauma (
    evento_id       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    consumo_alcohol TEXT,
    violencia       TEXT,
    envenenamiento  TEXT,
    lugar_evento    TEXT,
    CONSTRAINT uq_dim_evento_trauma UNIQUE NULLS NOT DISTINCT (
        consumo_alcohol, violencia, envenenamiento, lugar_evento)
);

CREATE TABLE IF NOT EXISTS trauma_completo.dim_tiempo (
    tiempo_id     INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha         DATE NOT NULL UNIQUE,
    dia           INTEGER,
    mes           INTEGER,
    nombre_mes    TEXT,
    trimestre     INTEGER,
    anio          INTEGER,
    dia_semana    TEXT,
    es_festivo    TEXT CHECK (es_festivo IN ('SI', 'NO'))   -- festivos de Colombia (incluye los trasladados por la Ley 51 de 1983)
);

-- Una fila por minuto del dia (1 440)
CREATE TABLE IF NOT EXISTS trauma_completo.dim_horario (
    horario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hora_larga TEXT    NOT NULL,                                  -- '12:00:00 a. m.'
    hora       INTEGER NOT NULL CHECK (hora BETWEEN 0 AND 23),
    minuto     INTEGER NOT NULL CHECK (minuto BETWEEN 0 AND 59),
    intervalo  TEXT    NOT NULL,                                  -- '00:00 - 01:00'
    CONSTRAINT uq_dim_horario UNIQUE (hora, minuto)
);

-- Mecanismos de lesion: grupos excluyentes, una dimension por grupo (cohesion). Una atencion sin ese
-- mecanismo apunta a la combinacion 'No aplica'. Las medidas (altura_metros, scq) van en el hecho.
-- Como fue la caida?
CREATE TABLE IF NOT EXISTS trauma_completo.dim_caida (
    caida_id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    caida           TEXT,
    tipo_superficie TEXT,
    CONSTRAINT uq_dim_caida UNIQUE NULLS NOT DISTINCT (caida, tipo_superficie)
);

-- Como fue la quemadura?
CREATE TABLE IF NOT EXISTS trauma_completo.dim_quemadura (
    quemadura_id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quemadura       TEXT,
    grado_quemadura TEXT,
    CONSTRAINT uq_dim_quemadura UNIQUE NULLS NOT DISTINCT (quemadura, grado_quemadura)
);

-- Como fue el accidente de transito?
CREATE TABLE IF NOT EXISTS trauma_completo.dim_accidente_transito (
    accidente_id       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    velocidad_colision TEXT,
    tipo_vehiculo      TEXT,
    ocupante           TEXT,
    tipo_colision      TEXT,
    CONSTRAINT uq_dim_accidente_transito UNIQUE NULLS NOT DISTINCT (
        velocidad_colision, tipo_vehiculo, ocupante, tipo_colision)
);

-- Que arma?
CREATE TABLE IF NOT EXISTS trauma_completo.dim_armas (
    armas_id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lesion_arma_fuego  TEXT,
    lesion_arma_blanca TEXT,
    CONSTRAINT uq_dim_armas UNIQUE NULLS NOT DISTINCT (lesion_arma_fuego, lesion_arma_blanca)
);

-- Como termino la atencion? En el Excel, las columnas sin el sufijo _hospitalizacion.
CREATE TABLE IF NOT EXISTS trauma_completo.dim_desenlace (
    desenlace_id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    disposicion_paciente TEXT,
    muerte_prevenible    TEXT,
    donacion_organos     TEXT,
    autopsia             TEXT,
    CONSTRAINT uq_dim_desenlace UNIQUE NULLS NOT DISTINCT (
        disposicion_paciente, muerte_prevenible, donacion_organos, autopsia)
);

-- Como se interpretan los signos vitales registrados? Calificadores de la primera toma por fecha y hora
-- (no se afirma que la toma sea al ingreso).
CREATE TABLE IF NOT EXISTS trauma_completo.dim_calificador_signos (
    calificador_signos_id               INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    perdida_conciencia                  TEXT,
    avup                                TEXT,
    calificador_gcs                     TEXT,
    calificador_frecuencia_respiratoria TEXT,
    CONSTRAINT uq_dim_calificador_signos UNIQUE NULLS NOT DISTINCT (
        perdida_conciencia, avup, calificador_gcs, calificador_frecuencia_respiratoria)
);

-- ===== CATALOGOS DE LOS PUENTES =====
-- Parte del cuerpo lesionada (examen fisico): vocabulario propio, con lateralidad
CREATE TABLE IF NOT EXISTS trauma_completo.dim_parte_cuerpo_lesion (
    parte_cuerpo_lesion_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parte_cuerpo           TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS trauma_completo.dim_mecanismo_primario (
    mecanismo_primario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mecanismo_primario    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS trauma_completo.dim_tipo_lesion (
    tipo_lesion_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo_lesion    TEXT NOT NULL UNIQUE
);

-- Catalogo unico de CIE-10 para el puente por rol y el de complicaciones.
-- Solo lineas CIE-10 mapeadas, mas el miembro 'SIN CODIGO CIE-10' para lo registrado sin pareja.
CREATE TABLE IF NOT EXISTS trauma_completo.dim_cie_10 (
    cie_10_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cie_10    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS trauma_completo.dim_sustancia (
    sustancia_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sustancia    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS trauma_completo.dim_procedimiento (
    procedimiento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    procedimientos   TEXT NOT NULL UNIQUE
);

-- Combinacion tipo de imagen + region estudiada (siempre se registran juntos). La descripcion libre
-- va en bridge_atencion_imagen, una por imagen realizada.
CREATE TABLE IF NOT EXISTS trauma_completo.dim_imagen (
    imagen_id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo_imagen  TEXT,
    parte_cuerpo TEXT,
    CONSTRAINT uq_dim_imagen UNIQUE NULLS NOT DISTINCT (tipo_imagen, parte_cuerpo)
);

-- ===== TABLA DE HECHOS =====
-- Una fila por atencion: claves, medidas y texto libre degenerado. Los signos vitales y los gases son
-- los de la primera toma por fecha y hora.
CREATE TABLE IF NOT EXISTS trauma_completo.fact_trauma (
    fact_id                     INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trauma_register_id          TEXT NOT NULL UNIQUE,
    fecha_admision_id           INTEGER,    -- llegada del paciente
    fecha_hospitalizacion_id    INTEGER,    -- admision a hospitalizacion
    fecha_alta_id               INTEGER,
    hora_alta_id                INTEGER,
    paciente_id                 INTEGER,
    evento_id                   INTEGER,
    caida_id                    INTEGER,
    quemadura_id                INTEGER,
    accidente_id                INTEGER,
    armas_id                    INTEGER,
    desenlace_id                INTEGER,
    calificador_signos_id       INTEGER,
    peso                        NUMERIC,
    altura                      NUMERIC,
    altura_metros               NUMERIC,    -- altura de la caida
    scq                         NUMERIC,
    gcs_ocular                  INTEGER,
    gcs_verbal                  INTEGER,
    gcs_motor                   INTEGER,
    duracion_perdida_conciencia NUMERIC,
    presion_sistolica           NUMERIC,
    presion_diastolica          NUMERIC,
    frecuencia_cardiaca         NUMERIC,
    frecuencia_respiratoria     NUMERIC,
    saturacion_o2               NUMERIC,
    temperatura_c               NUMERIC,
    pao2                        NUMERIC,
    paco2                       NUMERIC,
    iss                         NUMERIC,
    cabeza                      INTEGER,
    cara                        INTEGER,
    torax                       INTEGER,
    abdomen                     INTEGER,
    extremidades                INTEGER,
    externo                     INTEGER,
    dias_hospitalizacion        NUMERIC,
    uci_dias                    NUMERIC,
    sangre_l                    NUMERIC,
    motivo_consulta             TEXT,
    otras_sustancias_de_abuso   TEXT,       -- texto libre; no se mezcla con dim_sustancia
    detalles_hospitalizacion    TEXT,       -- texto libre, excluido del lector (04_permissions.sql)
    -- SHA-256 (hex) del contenido de la atencion, hecho y puentes; lo calcula el Loader para la carga
    -- incremental. NULL = fila sin huella: se trata como modificada. Excluida del lector.
    huella                      CHAR(64),
    CONSTRAINT ck_fact_huella CHECK (huella IS NULL OR huella ~ '^[0-9a-f]{64}$'),
    CONSTRAINT fk_fact_fecha_admision      FOREIGN KEY (fecha_admision_id)        REFERENCES trauma_completo.dim_tiempo (tiempo_id),
    CONSTRAINT fk_fact_fecha_hospitalizacion FOREIGN KEY (fecha_hospitalizacion_id) REFERENCES trauma_completo.dim_tiempo (tiempo_id),
    CONSTRAINT fk_fact_fecha_alta           FOREIGN KEY (fecha_alta_id)            REFERENCES trauma_completo.dim_tiempo (tiempo_id),
    CONSTRAINT fk_fact_hora_alta            FOREIGN KEY (hora_alta_id)             REFERENCES trauma_completo.dim_horario (horario_id),
    CONSTRAINT fk_fact_paciente             FOREIGN KEY (paciente_id)              REFERENCES trauma_completo.dim_paciente (paciente_id),
    CONSTRAINT fk_fact_evento               FOREIGN KEY (evento_id)                REFERENCES trauma_completo.dim_evento_trauma (evento_id),
    CONSTRAINT fk_fact_caida                FOREIGN KEY (caida_id)                 REFERENCES trauma_completo.dim_caida (caida_id),
    CONSTRAINT fk_fact_quemadura            FOREIGN KEY (quemadura_id)             REFERENCES trauma_completo.dim_quemadura (quemadura_id),
    CONSTRAINT fk_fact_accidente            FOREIGN KEY (accidente_id)             REFERENCES trauma_completo.dim_accidente_transito (accidente_id),
    CONSTRAINT fk_fact_armas                FOREIGN KEY (armas_id)                 REFERENCES trauma_completo.dim_armas (armas_id),
    CONSTRAINT fk_fact_desenlace            FOREIGN KEY (desenlace_id)             REFERENCES trauma_completo.dim_desenlace (desenlace_id),
    CONSTRAINT fk_fact_calificador_signos   FOREIGN KEY (calificador_signos_id)    REFERENCES trauma_completo.dim_calificador_signos (calificador_signos_id)
);

-- ===== TABLAS PUENTE (relaciones muchos-a-muchos con el hecho) =====
-- Una fila por lesion registrada: dos lesiones iguales en la misma atencion son dos lesiones (2026-10-27).
-- secuencia identifica la lesion dentro de la atencion (la asigna el Loader); no es un orden clinico.
-- En el Excel el mecanismo es uno por atencion y la carga lo copia a cada lesion; si falta, la carga apunta
-- al miembro 'Sin dato' (la columna admite NULL, pero la carga no deja nulos descriptivos).
-- REDCap puede repetir la misma lesion y el Excel no: el numero de lesiones por atencion no es comparable
-- entre fuentes; que lesiones hubo si.
CREATE TABLE IF NOT EXISTS trauma_completo.bridge_atencion_lesion (
    fact_id                INTEGER NOT NULL REFERENCES trauma_completo.fact_trauma (fact_id) ON DELETE CASCADE,
    secuencia              INTEGER NOT NULL CHECK (secuencia >= 1),
    parte_cuerpo_lesion_id INTEGER NOT NULL REFERENCES trauma_completo.dim_parte_cuerpo_lesion (parte_cuerpo_lesion_id),
    mecanismo_primario_id  INTEGER          REFERENCES trauma_completo.dim_mecanismo_primario (mecanismo_primario_id),
    tipo_lesion_id         INTEGER NOT NULL REFERENCES trauma_completo.dim_tipo_lesion (tipo_lesion_id),
    PRIMARY KEY (fact_id, secuencia)
);

-- Una fila por imagen realizada; secuencia = orden dentro de la atencion (lo asigna el Loader).
-- Dos imagenes del mismo tipo y region entran con secuencias distintas, cada una con su descripcion.
CREATE TABLE IF NOT EXISTS trauma_completo.bridge_atencion_imagen (
    fact_id            INTEGER NOT NULL REFERENCES trauma_completo.fact_trauma (fact_id) ON DELETE CASCADE,
    secuencia          INTEGER NOT NULL CHECK (secuencia >= 1),
    imagen_id          INTEGER NOT NULL REFERENCES trauma_completo.dim_imagen (imagen_id),
    descripcion_imagen TEXT,                    -- texto libre, excluido del lector (04_permissions.sql)
    PRIMARY KEY (fact_id, secuencia)
);

-- Un codigo CIE-10 de una atencion en un papel; una atencion solo tiene filas de los roles que registro.
-- El mismo codigo puede aparecer en dos roles de la misma atencion (el rol es parte de la clave).
-- Lo no mapeado apunta a 'SIN CODIGO CIE-10' y guarda su texto en texto_origen (NULL si el codigo esta mapeado).
-- Clave sustituta: texto_origen admite NULL y no puede ir en una PK; con UNIQUE NULLS NOT DISTINCT dos textos
-- distintos sin codigo entran y la repeticion exacta no (2026-10-27).
-- Roles (papel del codigo en la atencion):
--   diagnostico            diagnostico definitivo (confirmado). Excel y REDCap
--   comorbilidad           enfermedad previa del paciente. Excel y REDCap
--   mecanismo_transito     mecanismo de lesion de transito (capitulo V). Excel y REDCap
--   otro_mecanismo         mecanismo de lesion que no es de transito (capitulos V a Y). Excel y REDCap
-- Las complicaciones tienen su propio puente (con el lugar), bridge_atencion_complicacion.
-- El diagnostico de urgencias del Excel (Emergency Diagnosis) queda fuera por ahora: pendiente para una
-- implementacion futura como rol propio (impresion al ingreso, sin campo en REDCap).
CREATE TABLE IF NOT EXISTS trauma_completo.bridge_atencion_cie_10 (
    atencion_cie_10_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fact_id            INTEGER NOT NULL REFERENCES trauma_completo.fact_trauma (fact_id) ON DELETE CASCADE,
    cie_10_id          INTEGER NOT NULL REFERENCES trauma_completo.dim_cie_10 (cie_10_id),
    rol                TEXT    NOT NULL CHECK (rol IN (
        'diagnostico', 'comorbilidad', 'mecanismo_transito', 'otro_mecanismo')),
    texto_origen       TEXT,                    -- texto libre, excluido del lector (04_permissions.sql)
    CONSTRAINT uq_bridge_atencion_cie_10 UNIQUE NULLS NOT DISTINCT (fact_id, rol, cie_10_id, texto_origen)
);

-- El significado de cada rol queda tambien en el catalogo de PostgreSQL: lo muestran pgAdmin, DBeaver y el
-- navegador de Power BI al conectarse. COMMENT ON reemplaza el comentario anterior (idempotente).
COMMENT ON COLUMN trauma_completo.bridge_atencion_cie_10.rol IS
    'Papel del codigo CIE-10 en la atencion: diagnostico (definitivo, confirmado); comorbilidad (enfermedad '
    'previa); mecanismo_transito (lesion de transito, capitulo V); otro_mecanismo (lesion que no es de '
    'transito). Las complicaciones estan en bridge_atencion_complicacion.';

-- Una fila por complicacion distinta de la hospitalizacion (multivalor), con su codigo CIE-10 y su lugar.
-- Misma regla que bridge_atencion_cie_10: lo no mapeado guarda su texto; la repeticion exacta no entra.
CREATE TABLE IF NOT EXISTS trauma_completo.bridge_atencion_complicacion (
    complicacion_id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fact_id            INTEGER NOT NULL REFERENCES trauma_completo.fact_trauma (fact_id) ON DELETE CASCADE,
    cie_10_id          INTEGER NOT NULL REFERENCES trauma_completo.dim_cie_10 (cie_10_id),
    lugar_complicacion TEXT,
    texto_origen       TEXT,                    -- texto libre, excluido del lector (04_permissions.sql)
    CONSTRAINT uq_bridge_atencion_complicacion UNIQUE NULLS NOT DISTINCT (
        fact_id, cie_10_id, lugar_complicacion, texto_origen)
);

-- Una fila por sustancia de abuso registrada en la atencion. REDCap registra una sola (seleccion unica) y el
-- Excel varias: la prevalencia por sustancia es comparable entre fuentes; el numero de sustancias por atencion no.
CREATE TABLE IF NOT EXISTS trauma_completo.bridge_atencion_sustancia (
    fact_id      INTEGER NOT NULL REFERENCES trauma_completo.fact_trauma (fact_id) ON DELETE CASCADE,
    sustancia_id INTEGER NOT NULL REFERENCES trauma_completo.dim_sustancia (sustancia_id),
    PRIMARY KEY (fact_id, sustancia_id)
);

-- Una fila por procedimiento realizado; secuencia = orden dentro de la atencion (lo asigna el Loader).
-- La fecha de fin no se guarda: es inicio + duracion.
CREATE TABLE IF NOT EXISTS trauma_completo.bridge_atencion_procedimiento (
    fact_id          INTEGER NOT NULL REFERENCES trauma_completo.fact_trauma (fact_id) ON DELETE CASCADE,
    secuencia        INTEGER NOT NULL CHECK (secuencia >= 1),
    procedimiento_id INTEGER NOT NULL REFERENCES trauma_completo.dim_procedimiento (procedimiento_id),
    fecha_inicio_id  INTEGER REFERENCES trauma_completo.dim_tiempo (tiempo_id),
    hora_inicio_id   INTEGER REFERENCES trauma_completo.dim_horario (horario_id),
    duracion_seg     INTEGER CHECK (duracion_seg >= 0),
    PRIMARY KEY (fact_id, secuencia)
);
