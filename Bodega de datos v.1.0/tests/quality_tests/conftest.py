"""
Fixtures de las pruebas de calidad sobre la bodega cargada. Usan la base de pruebas (DB_NAME_TEST) con el
staging sintético de tests/fixtures/staging_sintetico.py: ningún dato real. La bodega se carga una vez por módulo con las
dos fuentes; cada prueba inyecta su defecto dentro de una transacción que se revierte.
"""
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from etl.load.warehouse.completo_loader import CompletoLoader
from etl.load.warehouse.contrato import leer_contrato
from tests.fixtures.staging_sintetico import generar_staging

RAIZ = Path(__file__).resolve().parents[2]
CONTRATO = RAIZ / "config" / "contratos" / "completo.yaml"
HOY = date(2026, 10, 27)   # fija el rango del calendario: 2011-01-01 a 2027-12-31


def _vaciar(motor) -> None:
    """Deja vacíos el esquema trauma_completo y etl_control.carga (con su detalle). Solo toca la base de pruebas."""
    with motor.begin() as c:
        tablas = c.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'trauma_completo' AND table_type = 'BASE TABLE'"
        )).scalars().all()
        lista = ", ".join([f"trauma_completo.{t}" for t in tablas] + ["etl_control.carga"])
        c.execute(text(f"TRUNCATE {lista} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="module")
def contrato():
    """Contrato real del modelo completo (solo el YAML versionado; no lee datos)."""
    return leer_contrato(str(CONTRATO), "completo")


@pytest.fixture(scope="module")
def staging_dirs(contrato, tmp_path_factory):
    """
    Carpetas del staging sintético de cada fuente ({fuente: carpeta}), generadas una vez por módulo. Es sintético y
    determinista (semilla fija): sin datos reales.
    """
    base = tmp_path_factory.mktemp("calidad")
    return {fuente: str(generar_staging(base / "staging" / fuente, fuente, contrato).carpeta)
            for fuente in ("excel", "redcap")}


@pytest.fixture(scope="module")
def bodega_cargada(motor_app, staging_dirs, tmp_path_factory):
    """
    Carga el Excel y luego REDCap con ese staging sintético en la base de pruebas y la vacía al terminar el módulo.
    """
    _vaciar(motor_app)
    for fuente, carpeta in staging_dirs.items():
        CompletoLoader(fuente=fuente, engine=motor_app, staging_dir=carpeta, ruta_contrato=str(CONTRATO),
                       quarantine_dir=str(tmp_path_factory.mktemp("cuarentena")), hoy=HOY).run()
    yield motor_app
    _vaciar(motor_app)


@pytest.fixture
def conexion(bodega_cargada):
    """
    Conexión con transacción que se revierte al terminar cada prueba: la prueba inyecta su defecto (incluso DDL, que
    PostgreSQL también revierte) sin alterar la bodega cargada del módulo.
    """
    with bodega_cargada.connect() as c:
        transaccion = c.begin()
        try:
            yield c
        finally:
            transaccion.rollback()
