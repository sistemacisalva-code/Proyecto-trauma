-- ============================================================
-- PERMISOS DEL ROL LECTOR (Power BI) sobre trauma_completo y trauma_mini
-- Se ejecuta desde main.py con el engine de la aplicacion (dueño de los objetos).
-- Los marcadores DB_NAME, DB_READER_USER, ESQUEMAS y ESQUEMAS_LITERALES se
-- sustituyen con .format(); los esquemas salen de MODELOS_ACTIVOS en main.py.
-- Idempotente: primero revoca y luego concede, asi el resultado siempre
-- coincide con lo declarado aqui.

-- ============================================================

-- 1. Reinicio de privilegios de tabla y columna del lector
REVOKE ALL ON ALL TABLES IN SCHEMA {ESQUEMAS} FROM {DB_READER_USER};

-- 2. Acceso a la base de datos y a los esquemas (solo lectura)
GRANT CONNECT ON DATABASE {DB_NAME} TO {DB_READER_USER};
GRANT USAGE ON SCHEMA {ESQUEMAS} TO {DB_READER_USER};

-- 3. SELECT por columna, excluyendo las sensibles (Habeas Data).
-- Para excluir o incluir una columna, editar la lista con el formato
-- esquema.tabla.columna y volver a ejecutar main.py.
DO $$
DECLARE
    r RECORD;
    excluidas TEXT[] := ARRAY[
        -- Texto clinico libre del modelo completo (2026-10-26: direccion_evento, hallazgos_clinicos y
        -- otro_mecanismo salieron del modelo; 2026-10-27: texto de los CIE-10 sin codigo)
        'trauma_completo.fact_trauma.detalles_hospitalizacion',
        -- Huella de la carga incremental (2026-10-28): dato tecnico que el tablero no necesita
        'trauma_completo.fact_trauma.huella',
        'trauma_completo.bridge_atencion_imagen.descripcion_imagen',
        'trauma_completo.bridge_atencion_cie_10.texto_origen',
        'trauma_completo.bridge_atencion_complicacion.texto_origen'
        -- El modelo mini no tiene columnas excluidas: motivo_de_consulta lo requiere el tablero (2026-10-24)
    ];
BEGIN
    FOR r IN
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema IN ({ESQUEMAS_LITERALES})
          AND (table_schema || '.' || table_name || '.' || column_name) <> ALL (excluidas)
    LOOP
        EXECUTE format(
            'GRANT SELECT (%I) ON %I.%I TO {DB_READER_USER}',
            r.column_name, r.table_schema, r.table_name
        );
    END LOOP;
END
$$;

-- No se usa ALTER DEFAULT PRIVILEGES: concederia SELECT completo sobre tablas
-- futuras y saltaria la exclusion de columnas. Las tablas nuevas quedan
-- cubiertas al re-ejecutar este script tras el DDL.
