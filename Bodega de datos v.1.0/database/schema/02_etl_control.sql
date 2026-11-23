-- ============================================================
-- ESQUEMA DE CONTROL DEL ETL: etl_control
-- Independiente de los modelos dimensionales (no depende de MODELOS_ACTIVOS).
-- Guarda el registro de corridas de extraccion para la guardia de idempotencia
-- de etl/pipeline.py (existe_corrida_exitosa / registrar_corrida_exitosa) y el de
-- corridas de carga a la bodega (una por modelo y fuente), con su detalle por uso, y el de las ejecuciones del
-- reporte de calidad de la bodega cargada.
-- El rol lector no recibe permisos sobre este esquema (ver 04_permissions.sql).
-- Idempotente: se puede re-ejecutar sin errores.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS etl_control;

CREATE TABLE IF NOT EXISTS etl_control.extraccion (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fuente          TEXT        NOT NULL,
    filas_extraidas INTEGER     NOT NULL CHECK (filas_extraidas >= 0),
    exitosa         BOOLEAN     NOT NULL,
    ejecutado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Consulta de la guardia: existe alguna corrida exitosa para la fuente
CREATE INDEX IF NOT EXISTS ix_extraccion_fuente_exitosa
    ON etl_control.extraccion (fuente, exitosa);

-- Corridas de carga a la bodega. Las filas son sumas sobre los usos del contrato (destino, tabla de
-- staging): una tabla que alimenta varios destinos suma una vez por destino. El detalle por uso esta en
-- etl_control.carga_detalle. Una corrida exitosa debe reconciliar (QR-EXA-01, por uso: destino y tabla de staging):
-- origen = cargadas + no usadas (otra toma, sin valor, duplicado) + cuarentena. Una corrida fallida no
-- tiene detalle: su origen son las filas leidas del staging.
CREATE TABLE IF NOT EXISTS etl_control.carga (
    id               INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    modelo           TEXT        NOT NULL,
    fuente           TEXT        NOT NULL,
    run_id_staging   TEXT        NOT NULL,
    filas_origen     INTEGER     NOT NULL CHECK (filas_origen >= 0),
    filas_cargadas   INTEGER     NOT NULL CHECK (filas_cargadas >= 0),
    filas_no_usadas  INTEGER     NOT NULL CHECK (filas_no_usadas >= 0),
    filas_cuarentena INTEGER     NOT NULL CHECK (filas_cuarentena >= 0),
    -- Atenciones de la fuente segun la carga incremental. Las filas de arriba no cambian de significado
    -- (filas del staging representadas en la bodega), asi que la reconciliacion de abajo sigue igual.
    atenciones_nuevas      INTEGER NOT NULL DEFAULT 0 CHECK (atenciones_nuevas >= 0),
    atenciones_modificadas INTEGER NOT NULL DEFAULT 0 CHECK (atenciones_modificadas >= 0),
    atenciones_sin_cambio  INTEGER NOT NULL DEFAULT 0 CHECK (atenciones_sin_cambio >= 0),
    atenciones_eliminadas  INTEGER NOT NULL DEFAULT 0 CHECK (atenciones_eliminadas >= 0),
    -- Carpeta de la cuarentena de la corrida (Parquet fuera de la base). Hay ruta si y solo si hubo filas
    -- apartadas; una corrida fallida tambien la guarda porque la cuarentena se escribe antes de la transaccion.
    ruta_cuarentena  TEXT,
    exitosa          BOOLEAN     NOT NULL,
    ejecutado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_carga_reconciliacion CHECK (
        NOT exitosa OR filas_origen = filas_cargadas + filas_no_usadas + filas_cuarentena),
    CONSTRAINT ck_carga_ruta_cuarentena CHECK ((filas_cuarentena = 0) = (ruta_cuarentena IS NULL))
);

-- Una fila por uso (destino, tabla de staging) de cada carga. destino es la tabla de la bodega o el
-- bloque de un puente por rol ('bridge_atencion_cie_10[diagnostico]'). Solo conteos, nunca datos.
--   otra_toma   filas de una tabla con toma: primera que no fueron la toma elegida
--   sin_valor   filas sin ningun valor en las columnas que pide el contrato
--   duplicado   repeticiones exactas unidas en un puente
-- Cada uso reconcilia por si solo.
CREATE TABLE IF NOT EXISTS etl_control.carga_detalle (
    carga_id      INTEGER NOT NULL REFERENCES etl_control.carga (id) ON DELETE CASCADE,
    destino       TEXT    NOT NULL,
    tabla_staging TEXT    NOT NULL,
    leidas        INTEGER NOT NULL CHECK (leidas >= 0),
    cargadas      INTEGER NOT NULL CHECK (cargadas >= 0),
    otra_toma     INTEGER NOT NULL DEFAULT 0 CHECK (otra_toma >= 0),
    sin_valor     INTEGER NOT NULL DEFAULT 0 CHECK (sin_valor >= 0),
    duplicado     INTEGER NOT NULL DEFAULT 0 CHECK (duplicado >= 0),
    cuarentena    INTEGER NOT NULL DEFAULT 0 CHECK (cuarentena >= 0),
    PRIMARY KEY (carga_id, destino, tabla_staging),
    CONSTRAINT ck_carga_detalle_reconciliacion CHECK (
        leidas = cargadas + otra_toma + sin_valor + duplicado + cuarentena)
);

-- Consulta de la guardia de la carga del Excel: existe una carga exitosa para (modelo, fuente)
CREATE INDEX IF NOT EXISTS ix_carga_modelo_fuente_exitosa
    ON etl_control.carga (modelo, fuente, exitosa);

-- Veredicto del reporte de calidad de la bodega cargada (etl/pipeline.py run_quality). Una fila por ejecucion del
-- reporte: es un evento distinto de la carga (puede repetirse sin cargar), por eso no vive en etl_control.carga.
-- Solo conteos, el veredicto y la carpeta del reporte; nunca filas ni valores. reglas_advierten incluye las que solo
-- informan. El rol lector no tiene acceso a este esquema (ver 04_permissions.sql).
CREATE TABLE IF NOT EXISTS etl_control.calidad (
    id               INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    modelo           TEXT        NOT NULL,
    veredicto        TEXT        NOT NULL CHECK (veredicto IN ('Aprobada', 'Aprobada con advertencias', 'Rechazada')),
    reglas_cumplen   INTEGER     NOT NULL CHECK (reglas_cumplen >= 0),
    reglas_advierten INTEGER     NOT NULL CHECK (reglas_advierten >= 0),
    reglas_fallan    INTEGER     NOT NULL CHECK (reglas_fallan >= 0),
    ruta_reporte     TEXT        NOT NULL,
    ejecutado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ultimo veredicto de un modelo
CREATE INDEX IF NOT EXISTS ix_calidad_modelo
    ON etl_control.calidad (modelo, ejecutado_en DESC);
