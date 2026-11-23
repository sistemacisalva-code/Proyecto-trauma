"""
Fixtures compartidos. Las pruebas de integracion usan una base PostgreSQL dedicada
(DB_NAME_TEST) que se crea con main.inicializar_bodega_de_datos() y se elimina al terminar.
Guardas: el nombre debe terminar en "_test" y no puede coincidir con la BD de desarrollo
ni la de produccion, para que una prueba nunca toque datos reales.
"""
import os
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

import main
from config.settings import DATABASE_YAML_PATH, admin_config

RAIZ = Path(__file__).resolve().parents[1]

CARPETA_A_MARCADOR = {
    "etl_tests": "unit",
    "integration_tests": "integration",
    "quality_tests": "quality",
    "acceptance_tests": "acceptance",
}


def pytest_collection_modifyitems(items):
    """Asigna el marcador de nivel segun la carpeta de la prueba."""
    for item in items:
        for carpeta, marcador in CARPETA_A_MARCADOR.items():
            if carpeta in item.path.parts:
                item.add_marker(getattr(pytest.mark, marcador))


def _url(cfg: dict, usuario: str, clave: str, base: str) -> URL:
    return URL.create(
        drivername=cfg["adapter"],
        username=usuario,
        password=clave,
        host=cfg["host"],
        port=int(cfg["port"]),
        database=base,
    )


def _eliminar_bd(cfg: dict, nombre: str) -> None:
    motor = create_engine(
        _url(cfg, admin_config["admin_user"], admin_config["admin_password"], "postgres"),
        isolation_level="AUTOCOMMIT",
    )
    with motor.connect() as c:
        quote = motor.dialect.identifier_preparer.quote
        c.execute(text(f"DROP DATABASE IF EXISTS {quote(nombre)} WITH (FORCE)"))
    motor.dispose()


@pytest.fixture(scope="session")
def bd_prueba():
    """Crea la BD de pruebas con el DDL real y devuelve su configuracion (dict)."""
    nombre = os.environ.get("DB_NAME_TEST")
    if not nombre:
        pytest.skip("Falta la variable DB_NAME_TEST en el entorno o en el .env")
    if not nombre.endswith("_test"):
        pytest.exit(f"DB_NAME_TEST debe terminar en '_test' (valor actual: '{nombre}').", returncode=2)
    if nombre in {os.environ.get("DB_NAME_DEV"), os.environ.get("DB_NAME_PROD")}:
        pytest.exit("DB_NAME_TEST no puede coincidir con la BD de desarrollo ni con la de produccion.", returncode=2)

    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(RAIZ)
        mp.setenv("APP_ENV", "development")
        mp.setenv("DB_NAME_DEV", nombre)

        with open(DATABASE_YAML_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(os.path.expandvars(f.read()))["development"]
        assert cfg["database"] == nombre

        _eliminar_bd(cfg, nombre)
        main.inicializar_bodega_de_datos()
        try:
            yield cfg
        finally:
            _eliminar_bd(cfg, nombre)


@pytest.fixture(scope="session")
def motor_app(bd_prueba):
    """Motor con el rol de la aplicacion (dueno de los objetos)."""
    motor = create_engine(_url(bd_prueba, bd_prueba["username"], bd_prueba["password"], bd_prueba["database"]))
    yield motor
    motor.dispose()


@pytest.fixture(scope="session")
def motor_lector(bd_prueba):
    """Motor con el rol lector (el que usaria Power BI)."""
    motor = create_engine(
        _url(bd_prueba, bd_prueba["reader"], bd_prueba["reader_password"], bd_prueba["database"])
    )
    yield motor
    motor.dispose()


@pytest.fixture
def conexion(motor_app):
    """Conexion con transaccion que se revierte al terminar cada prueba."""
    with motor_app.connect() as c:
        transaccion = c.begin()
        try:
            yield c
        finally:
            transaccion.rollback()


@pytest.fixture
def codigo_error(conexion):
    """Ejecuta SQL dentro de un savepoint y devuelve el SQLSTATE del error (None si no falla)."""

    def _ejecutar(sql: str, **parametros):
        try:
            with conexion.begin_nested():
                conexion.execute(text(sql), parametros)
        except DBAPIError as error:
            return error.orig.pgcode
        return None

    return _ejecutar


@pytest.fixture
def codigo_lector(motor_lector):
    """Ejecuta SQL como lector, en una conexion nueva, y devuelve el SQLSTATE del error (None si no falla)."""

    def _ejecutar(sql: str):
        try:
            with motor_lector.connect() as c:
                c.execute(text(sql))
        except DBAPIError as error:
            return error.orig.pgcode
        return None

    return _ejecutar
