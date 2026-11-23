import os
import re
import yaml
from pathlib import Path
from sqlalchemy import create_engine, text
from config.settings import DATABASE_YAML_PATH, DATABASE_DIR, admin_config


def _dividir_sentencias_sql(script_sql: str) -> list[str]:
    """
    Divide un script en sentencias de nivel superior, tratando los bloques
    delimitados por $$ ... $$ (funciones/DO) como unidades indivisibles.
    """
    patron = re.compile(r"\$\$.*?\$\$", re.DOTALL)
    marcador = "\x00"
    bloques = iter(patron.findall(script_sql))
    script_enmascarado = patron.sub(marcador, script_sql)

    sentencias = []
    for parte in script_enmascarado.split(";"):
        parte = parte.strip()
        if not parte:
            continue
        if all(not l.strip() or l.strip().startswith("--") for l in parte.splitlines()):
            continue  # fragmento con solo comentarios: psycopg2 no acepta consultas vacias
        # Los fragmentos salen en el mismo orden que los bloques: cada marcador consume el siguiente
        parte = re.sub(marcador, lambda _: next(bloques), parte)
        sentencias.append(parte)
    return sentencias


# Unica lista a editar para activar o quitar un modelo dimensional.
# Cada modelo m usa los archivos 02_tables_m.sql y 03_indexes_m.sql y el esquema trauma_m.
# Quitar un modelo no borra su esquema de bases ya creadas: hay que hacerlo a mano con DROP SCHEMA.
MODELOS_ACTIVOS = ["completo", "mini"]

# Esquema de control del ETL: independiente de los modelos, se crea siempre y va primero.
SCRIPTS_CONTROL = ["02_etl_control.sql"]

ESQUEMAS = [f"trauma_{m}" for m in MODELOS_ACTIVOS]
SCRIPTS_DDL = SCRIPTS_CONTROL + [
    nombre
    for m in MODELOS_ACTIVOS
    for nombre in (f"02_tables_{m}.sql", f"03_indexes_{m}.sql")
]


def aplicar_esquemas_dimensionales(entorno_config: dict) -> None:
    """
    Etapa 2: crea el esquema de control del ETL y las tablas e indices de los modelos activos.
    Usa un engine distinto al administrativo, con las credenciales de la aplicacion,
    y una sola transaccion: si un script falla, se revierte todo.
    """
    url_app = (
        f"{entorno_config['adapter']}://{entorno_config['username']}:"
        f"{entorno_config['password']}@{entorno_config['host']}:"
        f"{entorno_config['port']}/{entorno_config['database']}"
    )
    app_engine = create_engine(url_app)
    schema_dir = DATABASE_DIR / "schema"

    with app_engine.begin() as conexion:
        for nombre in SCRIPTS_DDL:
            ruta = schema_dir / nombre
            if not ruta.exists():
                raise FileNotFoundError(f"No se encontro el archivo {ruta}")
            print(f"Ejecutando {nombre}...")
            conexion.execute(text(ruta.read_text(encoding="utf-8")))
        print("¡Esquemas dimensionales creados con exito!")

    app_engine.dispose()


def aplicar_permisos(entorno_config: dict) -> None:
    """
    Etapa 3: concede al rol lector acceso de solo lectura (04_permissions.sql).
    Se ejecuta con el engine de la aplicacion, que es dueno de los objetos.
    """
    url_app = (
        f"{entorno_config['adapter']}://{entorno_config['username']}:"
        f"{entorno_config['password']}@{entorno_config['host']}:"
        f"{entorno_config['port']}/{entorno_config['database']}"
    )
    app_engine = create_engine(url_app)
    ruta = DATABASE_DIR / "schema" / "04_permissions.sql"
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontro el archivo {ruta}")

    script = ruta.read_text(encoding="utf-8").format(
        DB_NAME=entorno_config['database'],
        DB_READER_USER=entorno_config['reader'],
        ESQUEMAS=", ".join(ESQUEMAS),
        ESQUEMAS_LITERALES=", ".join(f"'{e}'" for e in ESQUEMAS),
    )
    with app_engine.begin() as conexion:
        print("Aplicando permisos del rol lector...")
        conexion.execute(text(script))
        print("¡Permisos aplicados con exito!")

    app_engine.dispose()


def inicializar_bodega_de_datos():
    # 1. Leer el entorno actual desde database.yaml
    with open(DATABASE_YAML_PATH, "r", encoding="utf-8") as f:
        contenido = os.path.expandvars(f.read())
        config_completa = yaml.safe_load(contenido)

    entorno = os.environ.get("APP_ENV", "development")
    entorno_config = config_completa[entorno]

    # 2. Conexion administrativa contra la BD de mantenimiento "postgres"
    url_admin = (
        f"{entorno_config['adapter']}://{admin_config['admin_user']}:"
        f"{admin_config['admin_password']}@{entorno_config['host']}:"
        f"{entorno_config['port']}/postgres"
    )
    admin_engine = create_engine(url_admin)
    print(f"--- Conectado como administrador al entorno [{entorno.upper()}] ---")

    # 3. Leer y ejecutar el script de roles/BD correspondiente al entorno activo
    sufijo = "dev" if entorno == "development" else "prod"
    ruta_roles_sql = DATABASE_DIR / "schema" / f"01_roles_and_db_{sufijo}.sql"

    if not ruta_roles_sql.exists():
        print(f"No se encontro el archivo {ruta_roles_sql}")
        return

    with open(ruta_roles_sql, "r", encoding="utf-8") as f:
        script_sql = f.read()
        script_sql_listo = script_sql.format(
            DB_USER=entorno_config['username'],
            DB_PASSWORD=entorno_config['password'],
            DB_READER_USER=entorno_config['reader'],
            DB_READER_PASSWORD=entorno_config['reader_password'],
            DB_NAME=entorno_config['database'],
        )

        # 4. Ejecucion en AUTOCOMMIT, sentencia por sentencia
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conexion:
        print("Ejecutando la configuracion inicial de roles y base de datos...")
        for sentencia in _dividir_sentencias_sql(script_sql_listo):
            conexion.execute(text(sentencia))
        print("¡Roles y permisos aplicados con exito!")

        # 5. Crear la BD solo si no existe (CREATE DATABASE no admite IF NOT EXISTS)
        nombre_bd = entorno_config['database']
        existe = conexion.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :nombre"),
            {"nombre": nombre_bd},
        ).scalar()
        if existe:
            print(f"La base de datos '{nombre_bd}' ya existe; se omite su creacion.")
        else:
            quote = admin_engine.dialect.identifier_preparer.quote
            conexion.execute(text(
                f"CREATE DATABASE {quote(nombre_bd)} WITH OWNER = {quote(entorno_config['username'])}"
            ))
            print(f"Base de datos '{nombre_bd}' creada.")

    admin_engine.dispose()

    # 6. Etapa 2: DDL de los modelos dimensionales (engine de aplicacion)
    aplicar_esquemas_dimensionales(entorno_config)

    # 7. Etapa 3: permisos del rol lector
    aplicar_permisos(entorno_config)


if __name__ == "__main__":
    inicializar_bodega_de_datos()
