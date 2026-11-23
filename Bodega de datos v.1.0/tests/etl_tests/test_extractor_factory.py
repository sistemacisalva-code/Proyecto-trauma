import pandas as pd
import pytest

from etl.extract.base import BaseExtractor
from etl.extract.excel_extractor import ExcelExtractor
from etl.extract.factory import ExtractorFactory


class _ExtractorSintetico(BaseExtractor):
    """Extractor mínimo y ficticio para probar el registro de nuevos orígenes (sin datos reales)."""

    source_type = "sintetico"

    def __init__(self, parametro):
        self.parametro = parametro

    def extract(self) -> pd.DataFrame:
        return pd.DataFrame()


@pytest.fixture
def registro_aislado(monkeypatch):
    """
    Sustituye el registro de la fábrica por una copia para la duración de la prueba.
    Aísla los tests: register() modifica un diccionario de clase y, sin esto,
    el tipo registrado quedaría disponible para el resto de la sesión.
    """
    monkeypatch.setattr(ExtractorFactory, "_registry", dict(ExtractorFactory._registry))


class TestExtractorFactoryGetExtractor:
    def test_unregistered_source_type_raises_valueerror(self):
        """
        Qué es: prueba unitaria de ExtractorFactory.get_extractor, rama de tipo no registrado.
        Qué hace: pide un extractor de un tipo de origen que no existe en el registro.
        Esperado: lanza ValueError y su mensaje nombra el tipo pedido y los tipos disponibles.
        """
        # Arrange: un tipo de origen inexistente en el registro
        tipo_invalido = "origen_inexistente"

        # Act + Assert: la fábrica debe rechazarlo con un mensaje que oriente al usuario
        with pytest.raises(ValueError, match="origen_inexistente") as error:
            ExtractorFactory.get_extractor(tipo_invalido, {})
        assert "excel" in str(error.value) and "redcap" in str(error.value)

    def test_invalid_config_raises_typeerror(self):
        """
        Qué es: prueba unitaria de ExtractorFactory.get_extractor, rama de configuración inválida.
        Qué hace: pide un extractor registrado pasando un parámetro que su constructor no acepta.
        Esperado: lanza TypeError con el mensaje "Configuración inválida" y el tipo de origen.
        """
        # Arrange: configuración con un parámetro inexistente en el constructor de REDCapExtractor
        config_invalida = {"parametro_inexistente": 1}

        # Act + Assert: el TypeError del constructor se envuelve con un mensaje claro
        with pytest.raises(TypeError, match="Configuración inválida para 'redcap'"):
            ExtractorFactory.get_extractor("redcap", config_invalida)

    def test_source_type_is_case_insensitive(self):
        """
        Qué es: prueba unitaria (control positivo) de ExtractorFactory.get_extractor.
        Qué hace: pide un extractor con el nombre del tipo en mayúsculas y una configuración válida.
        Esperado: devuelve una instancia de ExcelExtractor; el registro no distingue mayúsculas.
        """
        # Arrange: configuración válida; la ruta ficticia no se abre porque no se extrae nada
        config = {"source": "cualquier_ruta.xlsx", "sheet_name": 0}

        # Act: pedir el tipo en mayúsculas
        extractor = ExtractorFactory.get_extractor("EXCEL", config)

        # Assert: el tipo se normaliza a minúsculas antes de buscarlo en el registro
        assert isinstance(extractor, ExcelExtractor)


class TestExtractorFactoryRegister:
    def test_registered_type_can_be_instantiated(self, registro_aislado):
        """
        Qué es: prueba unitaria de ExtractorFactory.register (extensión sin modificar la clase).
        Qué hace: registra un extractor sintético con el nombre en mayúsculas y lo pide por su nombre.
        Esperado: get_extractor devuelve una instancia del extractor registrado, construida con la config.
        """
        # Arrange: el registro es una copia aislada (fixture) y el extractor es ficticio
        ExtractorFactory.register("SINTETICO", _ExtractorSintetico)

        # Act: pedir el nuevo tipo en minúsculas
        extractor = ExtractorFactory.get_extractor("sintetico", {"parametro": 7})

        # Assert: el tipo registrado se resuelve y recibe la configuración
        assert isinstance(extractor, _ExtractorSintetico)
        assert extractor.parametro == 7
