import pytest

from etl import pipeline
from etl.load.warehouse.base import LoadResult


@pytest.fixture
def fake_loader(monkeypatch):
    """
    Sustituye el engine y la fábrica de Loaders por dobles: no hay conexión a PostgreSQL ni lectura de staging.
    Registra con qué configuración se pide el Loader y si el engine se liberó; `error` hace fallar run().
    """
    estado = {"llamadas": [], "error": None, "dispose": 0}

    class EngineFalso:
        def dispose(self):
            estado["dispose"] += 1

    class LoaderFalso:
        def run(self):
            if estado["error"]:
                raise estado["error"]
            return LoadResult(modelo="completo", fuente="redcap", run_id_staging="2026-10-24T120000",
                              filas_origen={"t": 3}, filas_cuarentena={},
                              detalle={("fact_t", "t"): {"leidas": 3, "cargadas": 3, "otra_toma": 0, "sin_valor": 0,
                                                         "duplicado": 0, "cuarentena": 0}},
                              elapsed_seconds=0.1, loaded_at="2026-10-24T12:00:00+00:00")

    def get_loader(modelo, config):
        estado["llamadas"].append((modelo, config))
        return LoaderFalso()

    monkeypatch.setattr(pipeline, "_crear_engine", EngineFalso)
    monkeypatch.setattr(pipeline.LoaderFactory, "get_loader", staticmethod(get_loader))
    return estado


class TestRunLoad:
    def test_pide_el_loader_del_modelo_con_las_rutas_de_la_fuente(self, fake_loader, tmp_path):
        """
        Qué es: prueba unitaria de run_load con fábrica y engine simulados.
        Qué hace: ejecuta la carga de REDCap en el modelo completo con carpetas temporales.
        Esperado: la fábrica recibe "completo" con el staging de la fuente, el contrato <modelo>.yaml, la raíz de
                  la cuarentena y force; el engine se libera al terminar.
        """
        # Arrange: carpetas temporales (el doble no las lee)
        staging, contratos, cuarentena = (str(tmp_path / n) for n in ("staging", "contratos", "cuarentena"))

        # Act: cargar
        pipeline.run_load("completo", "redcap", force=False, staging_base_dir=staging,
                          contratos_dir=contratos, quarantine_dir=cuarentena)

        # Assert: configuración del Loader y engine liberado
        modelo, config = fake_loader["llamadas"][0]
        assert modelo == "completo"
        assert config["fuente"] == "redcap"
        assert config["staging_dir"].endswith("redcap")
        assert config["ruta_contrato"].endswith("completo.yaml")
        assert (config["quarantine_dir"], config["force"]) == (cuarentena, False)
        assert fake_loader["dispose"] == 1

    def test_libera_el_engine_aunque_la_carga_falle(self, fake_loader, tmp_path):
        """
        Qué es: prueba unitaria del manejo de errores de run_load.
        Qué hace: hace fallar run() del Loader simulado.
        Esperado: se propaga el error original y el engine igual se libera.
        """
        # Arrange: el Loader falla
        fake_loader["error"] = RuntimeError("El Excel ya se cargó (simulado)")

        # Act + Assert: error propagado
        with pytest.raises(RuntimeError, match="simulado"):
            pipeline.run_load("completo", "excel", staging_base_dir=str(tmp_path))

        # Assert: engine liberado
        assert fake_loader["dispose"] == 1
