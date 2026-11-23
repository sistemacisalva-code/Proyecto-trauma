from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from etl.extract.redcap_extractor import REDCapExtractor

# Datos sintéticos, generados artificialmente: nombres de variables genéricos y
# valores triviales. No provienen de REDCap ni de ningún registro del hospital
# (política de privacidad: cero datos clínicos reales en pruebas). Todas las
# pruebas usan además una URL y un token ficticios y simulan redcap.Project,
# de modo que no hay tráfico de red ni credenciales reales.
# Forma de lo que devuelve export_records con format_type="json": lista de dicts,
# una fila por registro-evento, con valores en texto (crudos, como los entrega REDCap).
SYNTHETIC_RECORDS = [
    {"record_id": "1", "redcap_event_name": "evento_1", "campo_generico_1": "a"},
    {"record_id": "1", "redcap_event_name": "evento_2", "campo_generico_1": "b"},
    {"record_id": "2", "redcap_event_name": "evento_1", "campo_generico_1": "c"},
]


class TestREDCapExtractorConstruction:
    def test_missing_credentials_raise_valueerror(self):
        """
        Qué es: prueba de validación del constructor de REDCapExtractor.
        Qué hace: crea el extractor con URL y token vacíos.
        Esperado: el constructor lanza ValueError de inmediato, sin contactar la API.
        """
        # Arrange: no aplica, las credenciales vacías se pasan directamente al constructor

        # Act + Assert: debe rechazarlas en el constructor (fail-fast), antes de cualquier llamada de red
        with pytest.raises(ValueError):
            REDCapExtractor(api_url="", api_token="")

    def test_source_type_class_attribute(self):
        """
        Qué es: prueba del contrato con BaseExtractor.
        Qué hace: crea un extractor válido (sin extraer nada) y lee su atributo source_type.
        Esperado: source_type vale "redcap"; run() lo necesita para etiquetar el resultado.
        """
        # Arrange: cualquier instancia válida, con URL y token ficticios (no se llega a extraer nada)
        extractor = REDCapExtractor(api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba")

        # Act: no aplica, se lee un atributo de clase

        # Assert: el atributo requerido por BaseExtractor.run() debe estar declarado
        assert extractor.source_type == "redcap"

    def test_extractor_never_exposes_write_operations(self):
        """
        Qué es: guardia de regresión de seguridad (política de solo lectura sobre REDCap).
        Qué hace: inspecciona los atributos propios de la clase REDCapExtractor.
        Esperado: ninguno de los métodos de escritura de PyCap (import_records, delete_records,
                  import_metadata) está declarado en la clase; si alguien lo agrega en el futuro,
                  la prueba falla antes de que el extractor pueda modificar la fuente.
        """
        # Arrange: nombres de los métodos de PyCap que escriben o borran en la fuente
        metodos_de_escritura = {"import_records", "delete_records", "import_metadata"}

        # Act: no aplica, se inspecciona la clase sin instanciarla

        # Assert: la intersección con los atributos propios de la clase debe ser vacía
        assert not metodos_de_escritura & set(vars(REDCapExtractor))


class TestREDCapExtractorExtract:
    @patch("etl.extract.redcap_extractor.redcap.Project")
    def test_extract_calls_export_records_only(self, mock_project_cls):
        """
        Qué es: prueba del caso normal de extract() (control positivo) con redcap.Project simulado.
        Qué hace: extrae registros indicando export_fields sintéticos, sin red ni token reales.
        Esperado: se llama export_records exactamente una vez, nunca import_records, y el
                  DataFrame devuelto trae las 3 filas sintéticas.
        """
        # Arrange: doble de redcap.Project que responde con los datos sintéticos
        mock_project = MagicMock()
        mock_project.export_records.return_value = SYNTHETIC_RECORDS
        mock_project_cls.return_value = mock_project

        extractor = REDCapExtractor(
            api_url="https://redcap.ejemplo.org/api/",
            api_token="token-de-prueba",
            export_fields=["record_id", "campo_generico_1"],
        )

        # Act: ejecutar la extracción
        df = extractor.extract()

        # Assert: solo se usó la operación de lectura; una de escritura sería una violación de la política
        mock_project.export_records.assert_called_once()
        mock_project.import_records.assert_not_called()
        assert len(df) == 3

    @patch("etl.extract.redcap_extractor.redcap.Project")
    def test_extract_keeps_record_id_as_column_with_raw_values(self, mock_project_cls):
        """
        Qué es: prueba del formato de salida para un proyecto longitudinal (capa raw).
        Qué hace: extrae registros sintéticos con un record_id repetido en dos eventos.
        Esperado: se pide format_type="json"; el DataFrame conserva record_id y redcap_event_name
                  como columnas (no como índice, o save_extraction_result los perdería con index=False),
                  las 3 filas (record_id repetido por evento) y los valores en crudo (texto).
        """
        # Arrange: doble de redcap.Project que responde con registros-evento sintéticos
        mock_project = MagicMock()
        mock_project.export_records.return_value = SYNTHETIC_RECORDS
        mock_project_cls.return_value = mock_project

        extractor = REDCapExtractor(api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba")

        # Act: ejecutar la extracción
        df = extractor.extract()

        # Assert: formato json solicitado, claves como columnas, una fila por registro-evento y sin conversión de tipos
        assert mock_project.export_records.call_args.kwargs["format_type"] == "json"
        assert list(df.columns) == ["record_id", "redcap_event_name", "campo_generico_1"]
        assert len(df) == 3
        assert df["record_id"].tolist() == ["1", "1", "2"]

    @patch("etl.extract.redcap_extractor.redcap.Project")
    def test_project_is_cached_across_multiple_extracts(self, mock_project_cls):
        """
        Qué es: prueba de gestión de recursos (el cliente de PyCap se cachea en self._project).
        Qué hace: llama a extract() dos veces sobre el mismo extractor.
        Esperado: redcap.Project se construye una sola vez; cubre la regresión en la que
                  _resolve_project asignaba a self.project (sin guion bajo) y nunca cacheaba.
        """
        # Arrange: doble de redcap.Project y un único extractor reutilizado en las dos llamadas
        mock_project = MagicMock()
        mock_project.export_records.return_value = SYNTHETIC_RECORDS
        mock_project_cls.return_value = mock_project

        extractor = REDCapExtractor(api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba")

        # Act: dos extracciones consecutivas con la misma instancia
        extractor.extract()
        extractor.extract()

        # Assert: el constructor de redcap.Project (que hace una llamada de metadata a la API) corrió una sola vez
        mock_project_cls.assert_called_once()

    @patch("etl.extract.redcap_extractor.redcap.Project")
    def test_extract_propagates_errors(self, mock_project_cls):
        """
        Qué es: prueba de manejo de errores de extract().
        Qué hace: simula que export_records falla (por ejemplo, por un token inválido).
        Esperado: la excepción se propaga tras registrarse en el log, sin ser tragada;
                  así el pipeline no registra una corrida exitosa sobre una extracción fallida.
        """
        # Arrange: doble de redcap.Project cuya exportación lanza una excepción
        mock_project = MagicMock()
        mock_project.export_records.side_effect = Exception("token invalido")
        mock_project_cls.return_value = mock_project

        extractor = REDCapExtractor(api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba")

        # Act + Assert: el error debe llegar al llamador, no ocultarse
        with pytest.raises(Exception):
            extractor.extract()

    @patch("etl.extract.redcap_extractor.redcap.Project")
    def test_extract_returns_empty_dataframe_when_no_records(self, mock_project_cls):
        """
        Qué es: prueba del caso borde de extract() cuando REDCap no devuelve registros.
        Qué hace: simula que export_records responde con una lista vacía.
        Esperado: extract() devuelve un DataFrame vacío (0 filas, 0 columnas) sin lanzar error;
                  el pipeline incremental depende de este comportamiento para tratar 0 filas
                  como corrida sin novedades y no como fallo.
        """
        # Arrange: doble de redcap.Project que responde sin registros
        mock_project = MagicMock()
        mock_project.export_records.return_value = []
        mock_project_cls.return_value = mock_project

        extractor = REDCapExtractor(api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba")

        # Act: ejecutar la extracción
        df = extractor.extract()

        # Assert: vacío y sin columnas, sin excepción
        assert df.empty
        assert len(df.columns) == 0

    @patch("etl.extract.redcap_extractor.redcap.Project")
    def test_extract_casts_repeat_instance_to_text(self, mock_project_cls):
        """
        Qué es: prueba de regresión de la capa raw (tipo único por columna para Parquet).
        Qué hace: simula registros donde redcap_repeat_instance llega como "" y como entero.
        Esperado: la columna queda toda en texto ("" y "2"); una columna con tipos mezclados
                  rompería la escritura a Parquet con pyarrow.
        """
        # Arrange: registros sintéticos con la mezcla de tipos que entrega REDCap
        registros = [
            {"record_id": "1", "redcap_repeat_instance": ""},
            {"record_id": "1", "redcap_repeat_instance": 2},
        ]
        mock_project = MagicMock()
        mock_project.export_records.return_value = registros
        mock_project_cls.return_value = mock_project

        extractor = REDCapExtractor(api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba")

        # Act: ejecutar la extracción
        df = extractor.extract()

        # Assert: todos los valores son texto y el entero se conserva como "2"
        assert df["redcap_repeat_instance"].tolist() == ["", "2"]
        assert all(isinstance(valor, str) for valor in df["redcap_repeat_instance"])
