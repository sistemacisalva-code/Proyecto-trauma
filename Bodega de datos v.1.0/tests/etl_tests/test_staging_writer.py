import json
import os

import pandas as pd
import pytest

from etl.load.staging_writer import run_id_de, save_transform_result
from etl.transform.base import TransformResult
from etl.transform.common.quality import ReporteCalidad

TRANSFORMADO_EN = "2026-10-08T17:30:05+00:00"


def _crear_resultado(transformed_at: str = TRANSFORMADO_EN, dato: int = 1) -> TransformResult:
    """Resultado de transformación sintético: dos tablas y un reporte con hallazgos mínimos.

    `dato` cambia el contenido de las tablas para distinguir una corrida de otra.
    """
    reporte = ReporteCalidad()
    reporte.registrar_auditoria("signos_vitales", "fc", pd.Series([60, 70, None]), pd.Series([60, 70, None]))
    reporte.reportar_regla("signos_vitales", "fc_en_rango", pd.Series([True, True]), pd.Series([False, True]))
    reporte.registrar_consolidacion({"particiones_leidas": 2, "filas_vigentes": 5})
    # Sin marcar_duplicados: la tabla "duplicados" queda vacía a propósito

    tablas = {
        "informacion_demografica": pd.DataFrame({"trauma_register_id": ["RC-1", "RC-2"], "valor": [dato, dato]}),
        "signos_vitales": pd.DataFrame({"trauma_register_id": ["RC-1"], "fc": [dato]}),
    }
    return TransformResult(
        tables=tablas, reporte=reporte, source_type="redcap",
        rows={nombre: len(df) for nombre, df in tablas.items()},
        elapsed_seconds=1.5, transformed_at=transformed_at,
    )


@pytest.fixture
def resultado():
    """TransformResult sintético (valores inventados, sin datos clínicos) con dos tablas y un reporte."""
    return _crear_resultado()


@pytest.fixture
def carpetas(tmp_path):
    """Carpetas de staging y reportes dentro del directorio temporal de la prueba (aisladas del repo)."""
    return str(tmp_path / "staging" / "redcap"), str(tmp_path / "reports")


class TestStagingWriterTablas:
    def test_escribe_un_parquet_por_tabla_con_sus_datos(self, resultado, carpetas, tmp_path):
        """
        Qué es: prueba unitaria de la escritura de tablas de save_transform_result.
        Qué hace: guarda un resultado sintético de dos tablas y relee los archivos generados.
        Esperado: existe un <tabla>.parquet por tabla en staging, junto al manifiesto, y cada uno es idéntico al
                  DataFrame original.
        """
        # Arrange: carpetas temporales del fixture
        staging, reportes = carpetas

        # Act: guardar el resultado
        rutas = save_transform_result(resultado, staging_dir=staging, reports_dir=reportes)

        # Assert: un archivo por tabla, sin pérdida de datos ni de tipos, y la ruta devuelta es la de staging
        assert rutas["staging"] == staging
        archivos = sorted(p.name for p in (tmp_path / "staging" / "redcap").iterdir())
        assert archivos == ["informacion_demografica.parquet", "manifiesto.json", "signos_vitales.parquet"]
        for nombre, df in resultado.tables.items():
            pd.testing.assert_frame_equal(pd.read_parquet(f"{staging}/{nombre}.parquet"), df)


class TestStagingWriterReemplazo:
    def test_segunda_corrida_reemplaza_el_staging_completo(self, carpetas, tmp_path):
        """
        Qué es: prueba unitaria de la sobrescritura del staging (foto derivada, no acumulativa).
        Qué hace: guarda una corrida con dos tablas y luego otra con datos distintos y una sola tabla.
        Esperado: el staging queda solo con la tabla y los datos de la segunda corrida; la tabla que
                  ya no se produce desaparece (no queda mezcla de corridas).
        """
        # Arrange: primera corrida ya guardada
        staging, reportes = carpetas
        save_transform_result(_crear_resultado(dato=1), staging_dir=staging, reports_dir=reportes)
        segunda = _crear_resultado(transformed_at="2026-10-09T08:00:00+00:00", dato=2)
        del segunda.tables["signos_vitales"]

        # Act: guardar la segunda corrida sobre la misma carpeta
        save_transform_result(segunda, staging_dir=staging, reports_dir=reportes)

        # Assert: solo la tabla nueva y con el contenido nuevo; sin carpetas auxiliares residuales
        assert sorted(p.name for p in (tmp_path / "staging").iterdir()) == ["redcap"]
        assert sorted(p.name for p in (tmp_path / "staging" / "redcap").iterdir()) == [
            "informacion_demografica.parquet", "manifiesto.json"]
        leido = pd.read_parquet(f"{staging}/informacion_demografica.parquet")
        assert leido["valor"].tolist() == [2, 2]

    def test_fallo_al_escribir_conserva_el_staging_anterior(self, carpetas, tmp_path, monkeypatch):
        """
        Qué es: prueba unitaria de la integridad del staging ante un fallo a mitad de la escritura.
        Qué hace: guarda una corrida buena y, en la siguiente, hace fallar la escritura de la segunda tabla.
        Esperado: se propaga el error, el staging conserva los archivos y datos de la corrida buena y no
                  quedan carpetas .tmp ni .old.
        """
        # Arrange: corrida buena ya guardada y un to_parquet que falla solo para signos_vitales
        staging, reportes = carpetas
        save_transform_result(_crear_resultado(dato=1), staging_dir=staging, reports_dir=reportes)
        original = pd.DataFrame.to_parquet

        def to_parquet_que_falla(self, path, *args, **kwargs):
            if os.path.basename(str(path)) == "signos_vitales.parquet":
                raise OSError("disco lleno (simulado)")
            return original(self, path, *args, **kwargs)

        monkeypatch.setattr(pd.DataFrame, "to_parquet", to_parquet_que_falla)

        # Act + Assert: la segunda corrida falla con el error simulado
        with pytest.raises(OSError, match="disco lleno"):
            save_transform_result(_crear_resultado(transformed_at="2026-10-09T08:00:00+00:00", dato=2),
                                  staging_dir=staging, reports_dir=reportes)

        # Assert: el staging sigue siendo el de la primera corrida y no quedan residuos
        assert sorted(p.name for p in (tmp_path / "staging").iterdir()) == ["redcap"]
        assert pd.read_parquet(f"{staging}/informacion_demografica.parquet")["valor"].tolist() == [1, 1]
        assert pd.read_parquet(f"{staging}/signos_vitales.parquet")["fc"].tolist() == [1]

    def test_descarta_un_temporal_residual_de_una_corrida_interrumpida(self, resultado, carpetas, tmp_path):
        """
        Qué es: prueba unitaria de la recuperación tras una corrida anterior interrumpida.
        Qué hace: deja una carpeta .tmp con un archivo ajeno (como si el proceso hubiera muerto) y guarda.
        Esperado: el staging final contiene solo las tablas del resultado; el archivo ajeno no se filtra.
        """
        # Arrange: residuo de una corrida interrumpida
        staging, reportes = carpetas
        residuo = tmp_path / "staging" / "redcap.tmp"
        residuo.mkdir(parents=True)
        (residuo / "basura.parquet").write_text("residuo")

        # Act: guardar normalmente
        save_transform_result(resultado, staging_dir=staging, reports_dir=reportes)

        # Assert: sin el archivo ajeno ni la carpeta temporal
        assert sorted(p.name for p in (tmp_path / "staging").iterdir()) == ["redcap"]
        assert sorted(p.name for p in (tmp_path / "staging" / "redcap").iterdir()) == [
            "informacion_demografica.parquet", "manifiesto.json", "signos_vitales.parquet"]


class TestStagingWriterReporte:
    def test_run_id_usa_el_formato_de_las_particiones_de_raw(self, resultado):
        """
        Qué es: prueba unitaria de run_id_de.
        Qué hace: calcula el identificador de corrida de un transformed_at conocido.
        Esperado: formato %Y-%m-%dT%H%M%S, sin ":" (válido como nombre de carpeta en Windows).
        """
        # Arrange: resultado con transformed_at fijo (fixture)

        # Act: calcular el identificador
        run_id = run_id_de(resultado)

        # Assert: coincide con el formato de las particiones load_date= de raw
        assert run_id == "2026-10-08T173005"

    def test_escribe_el_reporte_en_una_carpeta_por_corrida(self, resultado, carpetas, tmp_path):
        """
        Qué es: prueba unitaria de la ubicación y contenido del reporte de calidad.
        Qué hace: guarda el resultado y lista la carpeta de reportes.
        Esperado: existe reportes/redcap/run_id=<id>/ con un Parquet por tabla del reporte que tiene
                  contenido (auditoria, reglas, consolidacion), sin los de tablas vacías (duplicados), y el reporte.md.
        """
        # Arrange: el reporte sintético tiene auditoría, regla y consolidación, pero ningún duplicado
        staging, reportes = carpetas

        # Act: guardar el resultado
        rutas = save_transform_result(resultado, staging_dir=staging, reports_dir=reportes)

        # Assert: carpeta por corrida, solo con tablas no vacías, y los datos releídos coinciden con el reporte
        carpeta = tmp_path / "reports" / "redcap" / "run_id=2026-10-08T173005"
        assert rutas["reporte"] == str(carpeta)
        assert sorted(p.name for p in carpeta.iterdir()) == [
            "auditoria.parquet", "consolidacion.parquet", "manifiesto.json", "reglas.parquet", "reporte.md"]
        pd.testing.assert_frame_equal(pd.read_parquet(carpeta / "auditoria.parquet"),
                                      resultado.reporte.tabla("auditoria"))

    def test_manifiesto_resume_la_corrida(self, resultado, carpetas, tmp_path):
        """
        Qué es: prueba unitaria del manifiesto de la corrida.
        Qué hace: guarda el resultado y lee manifiesto.json.
        Esperado: contiene run_id, origen, momento, duración, las filas por tabla y la procedencia del resultado
                  (vacía en este resultado sintético).
        """
        # Arrange: carpetas temporales del fixture
        staging, reportes = carpetas

        # Act: guardar y leer el manifiesto
        save_transform_result(resultado, staging_dir=staging, reports_dir=reportes)
        ruta = tmp_path / "reports" / "redcap" / "run_id=2026-10-08T173005" / "manifiesto.json"
        manifiesto = json.loads(ruta.read_text(encoding="utf-8"))

        # Assert: el resumen coincide con el resultado
        assert manifiesto == {
            "run_id": "2026-10-08T173005", "source_type": "redcap", "transformed_at": TRANSFORMADO_EN,
            "elapsed_seconds": 1.5, "rows": {"informacion_demografica": 2, "signos_vitales": 1}, "procedencia": {},
        }

    def test_el_staging_lleva_el_mismo_manifiesto_que_el_reporte(self, carpetas, tmp_path):
        """
        Qué es: prueba unitaria del manifiesto copiado al staging (lo lee la carga a la bodega).
        Qué hace: guarda dos corridas y compara el manifiesto del staging con el de cada reporte.
        Esperado: el del staging es idéntico al del reporte de la última corrida, no al de la primera (viaja con
                  las tablas en el mismo intercambio).
        """
        # Arrange: dos corridas sobre las mismas carpetas
        staging, reportes = carpetas
        save_transform_result(_crear_resultado(dato=1), staging_dir=staging, reports_dir=reportes)
        save_transform_result(_crear_resultado(transformed_at="2026-10-09T08:00:00+00:00", dato=2),
                              staging_dir=staging, reports_dir=reportes)

        # Act: leer los tres manifiestos
        en_staging = json.loads((tmp_path / "staging" / "redcap" / "manifiesto.json").read_text(encoding="utf-8"))
        corridas = tmp_path / "reports" / "redcap"
        primero = json.loads((corridas / "run_id=2026-10-08T173005" / "manifiesto.json").read_text(encoding="utf-8"))
        ultimo = json.loads((corridas / "run_id=2026-10-09T080000" / "manifiesto.json").read_text(encoding="utf-8"))

        # Assert: el staging describe la última corrida
        assert en_staging == ultimo
        assert en_staging != primero

    def test_dos_corridas_dejan_dos_reportes_sin_pisarse(self, carpetas, tmp_path):
        """
        Qué es: prueba unitaria del historial de reportes (a diferencia del staging, no se sobrescribe).
        Qué hace: guarda dos resultados con distinto transformed_at.
        Esperado: dos carpetas run_id=..., cada una con su manifiesto, mientras staging queda con la última.
        """
        # Arrange: dos corridas en momentos distintos
        staging, reportes = carpetas

        # Act: guardar ambas sobre las mismas carpetas base
        save_transform_result(_crear_resultado(dato=1), staging_dir=staging, reports_dir=reportes)
        save_transform_result(_crear_resultado(transformed_at="2026-10-09T08:00:00+00:00", dato=2),
                              staging_dir=staging, reports_dir=reportes)

        # Assert: ambos reportes existen y el primero conserva su manifiesto original
        corridas = sorted(p.name for p in (tmp_path / "reports" / "redcap").iterdir())
        assert corridas == ["run_id=2026-10-08T173005", "run_id=2026-10-09T080000"]
        primero = json.loads((tmp_path / "reports" / "redcap" / corridas[0] / "manifiesto.json").read_text())
        assert primero["transformed_at"] == TRANSFORMADO_EN


class TestStagingWriterDetalleFilas:
    def test_escribe_detalle_filas_solo_con_llaves(self, carpetas, tmp_path):
        """
        Qué es: prueba unitaria de la escritura de la tabla detalle_filas del reporte.
        Qué hace: guarda un resultado cuyo reporte tiene una regla con llaves y lee detalle_filas.parquet.
        Esperado: el archivo existe junto a los demás del reporte y trae solo bloque, regla, tipo, columna, campos, llave
                  y filas: ninguna columna de valores de la tabla.
        """
        # Arrange: resultado sintético con una regla que identifica un registro
        resultado = _crear_resultado()
        resultado.reporte.reportar_regla("signos_vitales", "regla de prueba", pd.Series([True, True]),
                                         pd.Series([True, False]), pd.Series(["RC-1", "RC-2"]))
        staging, reportes = carpetas

        # Act
        rutas = save_transform_result(resultado, staging_dir=staging, reports_dir=reportes)

        # Assert
        detalle = pd.read_parquet(os.path.join(rutas["reporte"], "detalle_filas.parquet"))
        assert list(detalle.columns) == ["bloque", "regla", "tipo", "columna", "campos", "llave", "filas"]
        assert detalle["llave"].tolist() == ["RC-1"]
