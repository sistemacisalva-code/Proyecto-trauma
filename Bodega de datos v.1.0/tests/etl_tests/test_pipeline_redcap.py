from datetime import datetime

import pandas as pd
import pytest

from etl import pipeline


# Datos sintéticos para REDCap: variables genéricas, sin relación con el proyecto real.
SYNTHETIC_REDCAP_RECORDS = pd.DataFrame({
    "record_id": [1, 1, 2],
    "redcap_event_name": ["evento_1", "evento_2", "evento_1"],
    "campo_generico_1": ["a", "b", "c"],
})

# Config sintética local: nunca el REDCAP_EXPORT_CONFIG real de config/settings.py.
REDCAP_CONFIG = {
    "tabla_sintetica": {
        "export_fields": None,
        "dest": "redcap_sintetico",
        "expected_n_columns": None,
    },
}


@pytest.fixture
def fake_redcap(monkeypatch):
    """
    Sustituye la fábrica de extractores por un doble que devuelve datos sintéticos,
    de modo que no hay red, token ni proyecto REDCap reales. Registra los kwargs
    con que el pipeline construye el extractor.
    """
    from etl.extract.base import ExtractionResult

    llamadas = []

    class ExtractorFalso:
        def run(self):
            return ExtractionResult(
                data=SYNTHETIC_REDCAP_RECORDS,
                source_type="redcap",
                rows=len(SYNTHETIC_REDCAP_RECORDS),
                elapsed_seconds=0.0,
                extracted_at="2026-01-01T00:00:00+00:00",
            )

    def get_extractor(source_type, config):
        llamadas.append((source_type, config))
        return ExtractorFalso()

    monkeypatch.setattr(pipeline.ExtractorFactory, "get_extractor", staticmethod(get_extractor))
    return llamadas


class TestRunIncrementalRedcap:
    def test_writes_parquet_and_registers_run(self, tmp_path, control, fake_redcap):
        """
        Qué es: prueba unitaria de run_incremental_redcap (caso normal) con extractor simulado.
        Qué hace: ejecuta la extracción con una configuración sintética de una sola tabla.
        Esperado: un Parquet con el nombre "dest" dentro de una partición load_date=..., con los
                  mismos datos, y una corrida registrada con la fuente REDCap y el total de filas.
        """
        # Arrange: carpeta de salida temporal y datos sintéticos servidos por el doble
        base_dir = tmp_path / "raw"

        # Act: ejecutar la extracción de REDCap
        pipeline.run_incremental_redcap(
            base_dir=str(base_dir), export_config=REDCAP_CONFIG, api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba"
        )

        # Assert: datos idénticos, partición por corrida y corrida registrada con el total de filas
        archivos = list(base_dir.rglob("redcap_sintetico.parquet"))
        assert len(archivos) == 1
        assert archivos[0].parent.name.startswith("load_date=")
        pd.testing.assert_frame_equal(pd.read_parquet(archivos[0]), SYNTHETIC_REDCAP_RECORDS)
        assert control["registros"] == [(pipeline.REDCAP_CONTROL_SOURCE, len(SYNTHETIC_REDCAP_RECORDS))]

    def test_column_count_mismatch_fails_without_writing_or_registering(self, tmp_path, control, fake_redcap):
        """
        Qué es: prueba del control de deriva del esquema (expected_n_columns).
        Qué hace: configura un número de columnas esperado distinto al que devuelve el doble.
        Esperado: lanza ValueError antes de escribir nada y no registra ninguna corrida exitosa.
        """
        # Arrange: se esperan 99 columnas y el doble devuelve 3
        config = {"tabla_sintetica": {**REDCAP_CONFIG["tabla_sintetica"], "expected_n_columns": 99}}
        base_dir = tmp_path / "raw"

        # Act + Assert: la deriva de esquema debe detener la extracción
        with pytest.raises(ValueError, match="columnas"):
            pipeline.run_incremental_redcap(
                base_dir=str(base_dir), export_config=config, api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba"
            )

        # Assert: nada escrito ni registrado, para no dar por buena una extracción sospechosa
        assert not base_dir.exists()
        assert control["registros"] == []

    def test_zero_rows_does_not_trigger_column_mismatch(self, tmp_path, control, monkeypatch):
        """
        Qué es: prueba de regresión sobre el control de deriva del esquema (expected_n_columns).
        Qué hace: simula una corrida incremental sin registros nuevos ni modificados
                  (pd.DataFrame([]) da 0 filas y 0 columnas, el caso normal cuando nada
                  cambió desde la última corrida), con expected_n_columns configurado.
        Esperado: no lanza ValueError (0 filas no es deriva de esquema); se registra la
                  corrida exitosa con 0 filas extraídas.
        """
        # Arrange: doble que devuelve un DataFrame vacío (0 filas, 0 columnas), como
        # pd.DataFrame([]) cuando REDCap no tiene registros nuevos que exportar
        from etl.extract.base import ExtractionResult

        class ExtractorSinCambios:
            def run(self):
                return ExtractionResult(
                    data=pd.DataFrame([]),
                    source_type="redcap",
                    rows=0,
                    elapsed_seconds=0.0,
                    extracted_at="2026-01-01T00:00:00+00:00",
                )

        monkeypatch.setattr(
            pipeline.ExtractorFactory, "get_extractor", staticmethod(lambda source_type, config: ExtractorSinCambios())
        )
        config = {"tabla_sintetica": {**REDCAP_CONFIG["tabla_sintetica"], "expected_n_columns": 12}}
        base_dir = tmp_path / "raw"

        # Act: ejecutar la extracción incremental sin cambios pendientes
        pipeline.run_incremental_redcap(
            base_dir=str(base_dir), export_config=config, api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba"
        )

        # Assert: no revienta por 0 columnas y sí registra la corrida (0 filas es un resultado válido)
        assert control["registros"] == [(pipeline.REDCAP_CONTROL_SOURCE, 0)]

    def test_first_run_extracts_without_date_begin(self, tmp_path, control, fake_redcap):
        """
        Qué es: prueba de la ventana incremental en la primera corrida.
        Qué hace: ejecuta la extracción sin ninguna corrida exitosa previa registrada
                  (control["ultima_corrida"] queda en None, su valor por defecto).
        Esperado: el extractor se construye con date_begin=None, es decir, se pide el
                  histórico completo, sin filtrar por fecha de modificación.
        """
        # Arrange: sin corridas previas (comportamiento por defecto del fixture "control")
        base_dir = tmp_path / "raw"

        # Act: ejecutar la extracción de REDCap
        pipeline.run_incremental_redcap(
            base_dir=str(base_dir), export_config=REDCAP_CONFIG,
            api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba",
        )

        # Assert: la config con la que se construyó el extractor no trae fecha de corte
        _, config_usada = fake_redcap[0]
        assert config_usada["date_begin"] is None

    def test_subsequent_run_uses_last_successful_run_as_date_begin(self, tmp_path, control, fake_redcap):
        """
        Qué es: prueba de la ventana incremental en corridas posteriores a la primera.
        Qué hace: simula una corrida exitosa previa (control["ultima_corrida"]) y ejecuta
                  la extracción.
        Esperado: el extractor se construye con date_begin igual al timestamp de esa
                  corrida previa, para traer solo lo modificado desde entonces.
        """
        # Arrange: una corrida exitosa previa en un instante conocido
        ultima_corrida = datetime(2026, 1, 15, 8, 30, 0)
        control["ultima_corrida"] = ultima_corrida
        base_dir = tmp_path / "raw"

        # Act: ejecutar la extracción de REDCap
        pipeline.run_incremental_redcap(
            base_dir=str(base_dir), export_config=REDCAP_CONFIG,
            api_url="https://redcap.ejemplo.org/api/", api_token="token-de-prueba",
        )

        # Assert: la config con la que se construyó el extractor trae esa fecha como corte
        _, config_usada = fake_redcap[0]
        assert config_usada["date_begin"] == ultima_corrida
