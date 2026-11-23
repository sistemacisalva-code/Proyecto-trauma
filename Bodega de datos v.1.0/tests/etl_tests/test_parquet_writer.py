from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import pytest

from etl.load.parquet_writer import save_extraction_result


@dataclass
class FakeExtractionResult:
    """Doble simple de ExtractionResult, solo con lo que save_extraction_result necesita."""
    data: pd.DataFrame


@pytest.fixture
def fake_result():
    """Resultado de extracción sintético: 3 filas con las columnas id_evento y edad."""
    return FakeExtractionResult(data=pd.DataFrame({
        "id_evento": [1, 2, 3],
        "edad": [34, 58, 22],
    }))


def test_save_creates_file_with_expected_path(tmp_path, fake_result):
    """
    Qué es: prueba de la estructura de salida de save_extraction_result().
    Qué hace: guarda el resultado sintético con una fecha de carga fija en un directorio temporal.
    Esperado: la ruta devuelta es <base>/load_date=2026-09-22/registro_trauma.parquet y ese archivo
              existe en disco.
    """
    # Arrange: fecha de carga fija para poder predecir la ruta de salida
    load_date = "2026-09-22"

    # Act: guardar el resultado sintético como parquet
    ruta = save_extraction_result(
        fake_result, dest_name="registro_trauma", base_dir=str(tmp_path), load_date=load_date
    )

    # Assert: la ruta retornada y el archivo en disco siguen la estructura load_date=/dest.parquet
    assert ruta == str(tmp_path / f"load_date={load_date}" / "registro_trauma.parquet")
    assert (tmp_path / f"load_date={load_date}" / "registro_trauma.parquet").exists()


def test_save_returns_path_not_none(tmp_path, fake_result):
    """
    Qué es: prueba de regresión (bug corregido: la función devolvía None).
    Qué hace: guarda el resultado sin indicar fecha de carga.
    Esperado: devuelve la ruta del archivo como str, nunca None.
    """
    # Arrange: nada adicional, se usa el fixture tal cual

    # Act: guardar sin especificar load_date (usa el default de hoy)
    ruta = save_extraction_result(fake_result, dest_name="colisiones", base_dir=str(tmp_path))

    # Assert: debe devolver la ruta (string), no None -- bug corregido en to_parquet()
    assert ruta is not None
    assert isinstance(ruta, str)


def test_saved_parquet_roundtrips_data(tmp_path, fake_result):
    """
    Qué es: prueba de ida y vuelta (guardar y releer) del archivo parquet.
    Qué hace: guarda el resultado sintético y vuelve a leer el archivo generado con pyarrow.
    Esperado: el DataFrame leído es idéntico al original, con los mismos valores y los mismos tipos.
    """
    # Arrange: nada adicional, se usa el fixture tal cual

    # Act: guardar y volver a leer el mismo archivo parquet
    ruta = save_extraction_result(fake_result, dest_name="registro_trauma", base_dir=str(tmp_path))
    df_leido = pd.read_parquet(ruta, engine="pyarrow")

    # Assert: los datos leídos deben ser idénticos a los originales (sin pérdida de tipos)
    pd.testing.assert_frame_equal(df_leido, fake_result.data)


def test_default_load_date_uses_today(tmp_path, fake_result):
    """
    Qué es: prueba del valor por defecto de load_date.
    Qué hace: guarda el resultado sin pasar load_date y calcula la fecha de hoy por separado.
    Esperado: la ruta devuelta contiene la partición del día de hoy, load_date=AAAA-MM-DD.
    """
    # Arrange: fecha esperada = hoy, calculada igual que lo hace la función bajo prueba
    hoy = datetime.now().strftime("%Y-%m-%d")

    # Act: guardar sin pasar load_date explícitamente
    ruta = save_extraction_result(fake_result, dest_name="colisiones", base_dir=str(tmp_path))

    # Assert: la ruta debe contener la partición del día de hoy
    assert f"load_date={hoy}" in ruta
