import pandas as pd
import pytest

from etl import pipeline


def _resultado_transformacion(dato: int = 1):
    """TransformResult sintético de un transformer falso: una tabla y un reporte con una regla."""
    from etl.transform.base import TransformResult
    from etl.transform.common.quality import ReporteCalidad

    reporte = ReporteCalidad()
    reporte.reportar_regla("signos_vitales", "fc_en_rango", pd.Series([True, True]), pd.Series([False, True]))
    tablas = {"informacion_demografica": pd.DataFrame({"trauma_register_id": ["RC-1"], "valor": [dato]})}
    return TransformResult(
        tables=tablas, reporte=reporte, source_type="redcap", rows={"informacion_demografica": 1},
        elapsed_seconds=0.1, transformed_at="2026-10-08T17:30:05+00:00",
    )


@pytest.fixture
def fake_transformer(monkeypatch):
    """
    Sustituye la fábrica de transformers por un doble cuyo run() devuelve datos sintéticos o lanza el
    error configurado, de modo que no se lee raw ni se necesita una clave real. Registra los argumentos
    con que el pipeline pide el transformer.
    """
    estado = {"llamadas": [], "error": None, "resultado": _resultado_transformacion()}

    class TransformerFalso:
        def run(self):
            if estado["error"]:
                raise estado["error"]
            return estado["resultado"]

    def get_transformer(source_type, config):
        estado["llamadas"].append((source_type, config))
        return TransformerFalso()

    monkeypatch.setattr(pipeline.TransformerFactory, "get_transformer", staticmethod(get_transformer))
    return estado


class TestRunTransformRedcap:
    def test_escribe_staging_y_reporte(self, tmp_path, fake_transformer):
        """
        Qué es: prueba unitaria de run_transform_redcap (caso normal) con transformer simulado.
        Qué hace: ejecuta la transformación con carpetas temporales y una clave sintética.
        Esperado: la fábrica recibe el origen "redcap" con la clave y la carpeta raw; queda el Parquet
                  de la tabla en staging y una carpeta run_id=... con el reporte.
        """
        # Arrange: carpetas temporales y clave de prueba (no es una clave real)
        staging = tmp_path / "staging" / "redcap"

        # Act: ejecutar la transformación
        pipeline.run_transform_redcap(
            raw_dir=str(tmp_path / "raw"), staging_dir=str(staging),
            reports_dir=str(tmp_path / "reports"), clave_seudonimizacion="clave-de-prueba-de-16-bytes",
        )

        # Assert: configuración con que se creó el transformer, tabla en staging y reporte de la corrida
        assert fake_transformer["llamadas"] == [
            ("redcap", {"clave_seudonimizacion": "clave-de-prueba-de-16-bytes", "raw_dir": str(tmp_path / "raw")})
        ]
        pd.testing.assert_frame_equal(
            pd.read_parquet(staging / "informacion_demografica.parquet"),
            fake_transformer["resultado"].tables["informacion_demografica"],
        )
        assert (tmp_path / "reports" / "redcap" / "run_id=2026-10-08T173005" / "manifiesto.json").exists()

    def test_falla_del_transformer_deja_intacto_el_staging_anterior(self, tmp_path, fake_transformer):
        """
        Qué es: prueba unitaria de la protección del staging cuando la transformación falla
                (p. ej. la auditoría detecta una pérdida de datos).
        Qué hace: ejecuta una corrida buena y luego otra donde el transformer lanza ValueError.
        Esperado: el error se propaga, el staging conserva los datos de la corrida buena y no se crea
                  un reporte para la corrida fallida.
        """
        # Arrange: corrida buena ya guardada
        carpetas = dict(raw_dir=str(tmp_path / "raw"), staging_dir=str(tmp_path / "staging" / "redcap"),
                        reports_dir=str(tmp_path / "reports"), clave_seudonimizacion="clave-de-prueba-de-16-bytes")
        pipeline.run_transform_redcap(**carpetas)
        fake_transformer["error"] = ValueError("Variables con diferencia sin explicar: ['fc']")

        # Act + Assert: la segunda corrida falla con el error del transformer
        with pytest.raises(ValueError, match="diferencia sin explicar"):
            pipeline.run_transform_redcap(**carpetas)

        # Assert: staging y reportes siguen siendo los de la primera corrida
        leido = pd.read_parquet(tmp_path / "staging" / "redcap" / "informacion_demografica.parquet")
        assert leido["valor"].tolist() == [1]
        assert len(list((tmp_path / "reports" / "redcap").iterdir())) == 1
