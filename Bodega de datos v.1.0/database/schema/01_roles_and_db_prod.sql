-- 1. CREACION DE ROL DE PRODUCCION
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{DB_USER}') THEN
        CREATE ROLE {DB_USER} WITH LOGIN PASSWORD '{DB_PASSWORD}';
        RAISE NOTICE 'Usuario de produccion creado.';
    END IF;
END
$$;

-- 2. CREACION DE ROL DE LECTOR (PRODUCCION)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{DB_READER_USER}') THEN
        CREATE ROLE {DB_READER_USER} WITH LOGIN PASSWORD '{DB_READER_PASSWORD}';
        RAISE NOTICE 'Usuario de lectura del entorno de produccion creado.';
    END IF;
END
$$;

-- La base de datos se crea desde main.py solo si no existe
-- (CREATE DATABASE no admite IF NOT EXISTS).
