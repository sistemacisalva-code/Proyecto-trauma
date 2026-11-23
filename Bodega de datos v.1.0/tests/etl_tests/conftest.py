"""Fixtures compartidos por las pruebas unitarias de tests/etl_tests/."""
import pytest

from etl import pipeline
from etl.transform.common.quality import ReporteCalidad


@pytest.fixture
def reporte():
    """
    Crea un ReporteCalidad vacío por prueba. Es una instancia nueva en memoria, sin datos
    clínicos y sin estado compartido con otras pruebas (el reporte no es global).
    """
    return ReporteCalidad()


@pytest.fixture
def regla(reporte):
    """
    Devuelve una función `regla(bloque, fragmento) -> (filas_evaluables, filas_que_incumplen)` que busca,
    en el reporte de la prueba, la única regla del bloque cuyo nombre contiene el fragmento. Falla si
    ninguna o más de una coincide, para que un cambio de nombre no pase inadvertido. Solo lee conteos.
    """
    def _buscar(bloque: str, fragmento: str) -> tuple[int, int]:
        coincidencias = [v for (b, r), v in reporte.reglas.items() if b == bloque and fragmento in r]
        assert len(coincidencias) == 1, f"{bloque}: {len(coincidencias)} reglas contienen '{fragmento}'"
        return coincidencias[0]["filas_evaluables"], coincidencias[0]["filas_que_incumplen"]
    return _buscar


@pytest.fixture
def control(monkeypatch):
    """
    Sustituye la tabla de control de Postgres por dobles en memoria.
    Devuelve un dict para configurar la guardia y leer qué se registró.
    """
    estado = {"ya_cargado": False, "registros": [], "ultima_corrida": None}
    monkeypatch.setattr(pipeline, "existe_corrida_exitosa", lambda fuente: estado["ya_cargado"])
    monkeypatch.setattr(
        pipeline,
        "registrar_corrida_exitosa",
        lambda fuente, filas: estado["registros"].append((fuente, filas)),
    )
    monkeypatch.setattr(
        pipeline, "obtener_ultima_corrida_exitosa", lambda fuente: estado["ultima_corrida"]
    )
    return estado
