import pandas as pd
import pytest

from etl.extract.excel_extractor import ExcelExtractor


SYNTHETIC_SHEETS = {
    "hoja_principal": pd.DataFrame({
        "id_evento": [1, 2, 3],
        "edad": [34, 58, 22],
        "codigo_cie10": ["S06.0", "S72.0", "T14.9"],
    }),
    "hoja_seguimiento": pd.DataFrame({
        "id_evento": [1, 2],
        "dias_estancia": [4, 12],
    }),
}


@pytest.fixture
def synthetic_workbook_path(tmp_path):
    """Crea un .xlsx sintético (multi-hoja) en un directorio temporal aislado."""
    file_path = tmp_path / "workbook_sintetico.xlsx"
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        for sheet_name, df in SYNTHETIC_SHEETS.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return str(file_path)


class TestExcelExtractorConstruction:
    def test_invalid_source_type_raises_typeerror(self):
        """
        Qué es: prueba de validación del constructor de ExcelExtractor.
        Qué hace: crea el extractor con un "source" de tipo no soportado (un entero).
        Esperado: el constructor lanza TypeError de inmediato, sin llegar a leer ningún archivo.
        """
        # Arrange: un "source" con un tipo no soportado (ni str ni pd.ExcelFile)
        source_invalido = 123

        # Act + Assert: el constructor debe rechazarlo de inmediato
        with pytest.raises(TypeError):
            ExcelExtractor(source=source_invalido, sheet_name="hoja_principal")

    def test_source_type_class_attribute(self):
        """
        Qué es: prueba del contrato con BaseExtractor.
        Qué hace: crea un extractor válido (sin extraer nada) y lee su atributo source_type.
        Esperado: source_type vale "excel"; run() lo necesita para etiquetar el resultado.
        """
        # Arrange: cualquier instancia válida (no se llega a extraer nada)
        extractor = ExcelExtractor(source="cualquier_ruta.xlsx", sheet_name=0)

        # Act: no aplica, se lee un atributo de clase

        # Assert: el atributo requerido por BaseExtractor.run() debe estar declarado
        assert extractor.source_type == "excel"


class TestExcelExtractorFromPath:
    def test_missing_file_raises_filenotfounderror(self):
        """
        Qué es: prueba de manejo de errores al extraer desde una ruta.
        Qué hace: llama a extract() con la ruta de un archivo que no existe.
        Esperado: lanza FileNotFoundError, con un mensaje claro y no un AttributeError genérico.
        """
        # Arrange: una ruta que no existe en disco
        extractor = ExcelExtractor(source="ruta_que_no_existe.xlsx", sheet_name="hoja_principal")

        # Act + Assert: extract() debe fallar con un error claro, no un AttributeError genérico
        with pytest.raises(FileNotFoundError):
            extractor.extract()

    def test_extract_returns_expected_rows_and_columns(self, synthetic_workbook_path):
        """
        Qué es: prueba del caso normal de extract() (control positivo).
        Qué hace: extrae la hoja "hoja_principal" del workbook sintético.
        Esperado: devuelve un DataFrame con las mismas filas y las mismas columnas que los datos originales
                  (3 filas; id_evento, edad y codigo_cie10).
        """
        # Arrange: extractor apuntando a la hoja "hoja_principal" del workbook sintético
        extractor = ExcelExtractor(source=synthetic_workbook_path, sheet_name="hoja_principal", engine="openpyxl")

        # Act: ejecutar la extracción
        df = extractor.extract()

        # Assert: el DataFrame debe coincidir en forma y columnas con los datos sintéticos originales
        assert isinstance(df, pd.DataFrame)
        assert len(df) == len(SYNTHETIC_SHEETS["hoja_principal"])
        assert list(df.columns) == list(SYNTHETIC_SHEETS["hoja_principal"].columns)

    def test_invalid_sheet_name_raises_valueerror(self, synthetic_workbook_path):
        """
        Qué es: prueba de manejo de errores con una hoja inexistente.
        Qué hace: extrae una hoja que no está en el workbook sintético.
        Esperado: lanza ValueError con un mensaje de negocio, no un KeyError crudo de pandas.
        """
        # Arrange: extractor apuntando a una hoja que no existe en el workbook
        extractor = ExcelExtractor(source=synthetic_workbook_path, sheet_name="hoja_inexistente", engine="openpyxl")

        # Act + Assert: debe fallar con un mensaje de negocio, no con un KeyError crudo de pandas
        with pytest.raises(ValueError):
            extractor.extract()

    def test_owned_handle_is_closed_after_extract(self, synthetic_workbook_path):
        """
        Qué es: prueba de gestión de recursos (el extractor cierra lo que abrió).
        Qué hace: extrae desde una ruta, lo que hace que el extractor abra su propio ExcelFile, y luego
                  intenta volver a leer una hoja con ese manejador.
        Esperado: la segunda lectura falla con una excepción, porque el archivo quedó cerrado.
        """
        # Arrange: extractor que abrió el archivo él mismo (_owns_handle=True, por pasar un path)
        extractor = ExcelExtractor(source=synthetic_workbook_path, sheet_name="hoja_principal", engine="openpyxl")

        # Act: extraer, lo que debe cerrar el handle propio al finalizar
        extractor.extract()

        # Assert: tras cerrar, ExcelFile no permite volver a parsear
        with pytest.raises(Exception):
            extractor._excel_file.parse(sheet_name="hoja_principal")


class TestExcelExtractorFromSharedWorkbook:
    def test_shared_excel_file_is_not_closed(self, synthetic_workbook_path):
        """
        Qué es: prueba de gestión de recursos con un workbook compartido.
        Qué hace: abre un pd.ExcelFile a mano, lo pasa a dos extractores (una hoja cada uno) y extrae con ambos.
        Esperado: las dos extracciones traen las filas correctas (3 y 2) y el workbook compartido sigue
                  utilizable después, porque el extractor no cierra lo que no abrió.
        """
        # Arrange: un pd.ExcelFile abierto manualmente y compartido entre dos extractores
        shared_excel_file = pd.ExcelFile(synthetic_workbook_path, engine="openpyxl")
        extractor_1 = ExcelExtractor(source=shared_excel_file, sheet_name="hoja_principal")
        extractor_2 = ExcelExtractor(source=shared_excel_file, sheet_name="hoja_seguimiento")

        # Act: extraer con ambos extractores usando el mismo workbook
        df_1 = extractor_1.extract()
        df_2 = extractor_2.extract()

        # Assert: ambas extracciones son correctas y el workbook compartido sigue usable después
        assert len(df_1) == len(SYNTHETIC_SHEETS["hoja_principal"])
        assert len(df_2) == len(SYNTHETIC_SHEETS["hoja_seguimiento"])
        assert shared_excel_file.parse(sheet_name="hoja_principal") is not None

        shared_excel_file.close()


class TestExcelExtractorRunTemplateMethod:
    def test_run_returns_extraction_result_with_metadata(self, synthetic_workbook_path):
        """
        Qué es: prueba del Template Method run() de BaseExtractor.
        Qué hace: ejecuta run() en lugar de extract() sobre el workbook sintético.
        Esperado: un ExtractionResult con source_type "excel", rows igual a 3, elapsed_seconds mayor o
                  igual a 0 y extracted_at no vacío (metadatos de trazabilidad).
        """
        # Arrange: extractor válido sobre el workbook sintético
        extractor = ExcelExtractor(source=synthetic_workbook_path, sheet_name="hoja_principal", engine="openpyxl")

        # Act: usar run() (Template Method de BaseExtractor), no extract() directo
        result = extractor.run()

        # Assert: el resultado debe traer los datos junto con metadata de trazabilidad
        assert result.source_type == "excel"
        assert result.rows == len(SYNTHETIC_SHEETS["hoja_principal"])
        assert result.elapsed_seconds >= 0
        assert result.extracted_at


class TestExcelExtractorListSheets:
    def test_list_sheets_returns_all_sheet_names(self, synthetic_workbook_path):
        """
        Qué es: prueba del método estático list_sheets().
        Qué hace: pide la lista de hojas del workbook sintético sin abrirlo manualmente.
        Esperado: la lista coincide, en el mismo orden, con las hojas creadas por el fixture
                  (hoja_principal y hoja_seguimiento).
        """
        # Arrange: workbook sintético con hojas conocidas

        # Act: pedir la lista de hojas sin abrir el workbook manualmente
        sheets = ExcelExtractor.list_sheets(synthetic_workbook_path, engine="openpyxl")

        # Assert: deben coincidir exactamente con las hojas creadas en el fixture
        assert sheets == list(SYNTHETIC_SHEETS.keys())

    def test_list_sheets_missing_file_raises_filenotfounderror(self):
        """
        Qué es: prueba de manejo de errores de list_sheets().
        Qué hace: pide las hojas de un archivo que no existe.
        Esperado: lanza FileNotFoundError enseguida, sin intentar abrir el archivo.
        """
        # Arrange: una ruta inexistente

        # Act + Assert: debe fallar rápido, sin intentar abrir un archivo que no existe
        with pytest.raises(FileNotFoundError):
            ExcelExtractor.list_sheets("ruta_que_no_existe.xlsx", engine="openpyxl")


class TestExcelExtractorValidateConfiguredSheets:
    # sheets_config sintético local: nunca el EXCEL_SHEETS_CONFIG real de config/settings.py,
    # para no acoplar el test a nombres de hojas del hospital.
    VALID_SHEETS_CONFIG = {
        "hoja_principal": {"sheet_name": "hoja_principal", "dest": "principal"},
        "hoja_seguimiento": {"sheet_name": "hoja_seguimiento", "dest": "seguimiento"},
    }

    INVALID_SHEETS_CONFIG = {
        "hoja_principal": {"sheet_name": "hoja_principal", "dest": "principal"},
        "hoja_inexistente": {"sheet_name": "hoja_que_no_existe", "dest": "inexistente"},
    }

    def test_validate_passes_when_all_sheets_exist(self, synthetic_workbook_path):
        """
        Qué es: prueba de validate_configured_sheets() con una configuración correcta (control positivo).
        Qué hace: valida una configuración cuyas hojas existen todas en el workbook sintético.
        Esperado: no lanza ninguna excepción y no devuelve nada.
        """
        # Arrange: config sintética cuyas hojas SÍ existen en el workbook

        # Act + Assert: no debe lanzar ninguna excepción
        ExcelExtractor.validate_configured_sheets(
            synthetic_workbook_path, self.VALID_SHEETS_CONFIG, engine="openpyxl"
        )

    def test_validate_raises_valueerror_with_missing_sheet_names(self, synthetic_workbook_path):
        """
        Qué es: prueba de validate_configured_sheets() con una hoja faltante (fail-fast).
        Qué hace: valida una configuración que incluye una hoja que no existe en el workbook.
        Esperado: lanza ValueError y el mensaje incluye el nombre de la hoja faltante ("hoja_que_no_existe").
        """
        # Arrange: config sintética con una hoja que NO existe en el workbook

        # Act + Assert: debe fallar en fail-fast, con el nombre faltante en el mensaje de error
        with pytest.raises(ValueError) as exc_info:
            ExcelExtractor.validate_configured_sheets(
                synthetic_workbook_path, self.INVALID_SHEETS_CONFIG, engine="openpyxl"
            )

        assert "hoja_que_no_existe" in str(exc_info.value)
