"""
Fixtures de las pruebas de aceptación de indicadores. Reutilizan las de calidad: el contrato real del modelo
completo, el staging sintético (ningún dato real) y la bodega cargada una vez por módulo en la base de pruebas
(DB_NAME_TEST). Cada prueba consulta la bodega y compara con un cálculo independiente en pandas sobre ese staging.
"""
from tests.quality_tests.conftest import bodega_cargada, conexion, contrato, staging_dirs  # noqa: F401
