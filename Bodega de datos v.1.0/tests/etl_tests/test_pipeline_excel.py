import pandas as pd
import pytest

from etl import pipeline


SYNTHETIC_SHEETS = {
    "Hoja Uno": pd.DataFrame({"id_evento": [1, 2, 3], "edad": [34, 58, 22]}),
    "Hoja Dos": pd.DataFrame({"id_evento": [1, 2], "dias_estancia": [4, 12]}),
}

# Config sintética local: nunca el EXCEL_SHEETS_CONFIG real de config/settings.py.
SHEETS_CONFIG = {
    "hoja_uno": {"sheet_name": "Hoja Uno", "dest": "uno"},
    "hoja_dos": {"sheet_name": "Hoja Dos", "dest": "dos"},
}


@pytest.fixture
def synthetic_workbook_path(tmp_path):
    """Crea un .xlsx sintético con dos hojas en un directorio temporal aislado."""
    file_path = tmp_path / "workbook_sintetico.xlsx"
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        for sheet_name, df in SYNTHETIC_SHEETS.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return str(file_path)


def test_writes_one_parquet_per_configured_sheet(tmp_path, synthetic_workbook_path, control):
    # Arrange: workbook sintético con dos hojas y carpeta de salida temporal
    base_dir = tmp_path / "raw"

    # Act: ejecutar la carga histórica
    pipeline.run_historical_excel_load(
        source_path=synthetic_workbook_path, sheets_config=SHEETS_CONFIG, base_dir=str(base_dir)
    )

    # Assert: un parquet por hoja, nombrado con "dest", y los datos coinciden con los originales
    archivos = {p.name: p for p in base_dir.rglob("*.parquet")}
    assert set(archivos) == {"uno.parquet", "dos.parquet"}
    pd.testing.assert_frame_equal(pd.read_parquet(archivos["uno.parquet"]), SYNTHETIC_SHEETS["Hoja Uno"])
    pd.testing.assert_frame_equal(pd.read_parquet(archivos["dos.parquet"]), SYNTHETIC_SHEETS["Hoja Dos"])


def test_registers_successful_run_with_total_rows(tmp_path, synthetic_workbook_path, control):
    # Arrange: filas esperadas = suma de las filas de todas las hojas sintéticas
    filas_esperadas = sum(len(df) for df in SYNTHETIC_SHEETS.values())

    # Act: ejecutar la carga histórica
    pipeline.run_historical_excel_load(
        source_path=synthetic_workbook_path, sheets_config=SHEETS_CONFIG, base_dir=str(tmp_path / "raw")
    )

    # Assert: una sola corrida exitosa registrada, con la fuente y el total de filas correctos
    assert control["registros"] == [(pipeline.EXCEL_CONTROL_SOURCE, filas_esperadas)]


def test_raises_when_already_loaded_and_not_forced(tmp_path, synthetic_workbook_path, control):
    # Arrange: la tabla de control ya tiene una corrida exitosa
    control["ya_cargado"] = True
    base_dir = tmp_path / "raw"

    # Act + Assert: la guardia detiene la carga con un error claro
    with pytest.raises(RuntimeError):
        pipeline.run_historical_excel_load(
            source_path=synthetic_workbook_path, sheets_config=SHEETS_CONFIG, base_dir=str(base_dir)
        )

    # Assert: no se escribió nada ni se registró ninguna corrida nueva
    assert not base_dir.exists()
    assert control["registros"] == []


def test_force_repeats_load_even_if_already_loaded(tmp_path, synthetic_workbook_path, control):
    # Arrange: ya existe una corrida exitosa previa
    control["ya_cargado"] = True
    base_dir = tmp_path / "raw"

    # Act: repetir la carga de forma explícita con force=True
    pipeline.run_historical_excel_load(
        force=True, source_path=synthetic_workbook_path, sheets_config=SHEETS_CONFIG, base_dir=str(base_dir)
    )

    # Assert: la carga se ejecutó (hay parquets) y se registró la nueva corrida
    assert len(list(base_dir.rglob("*.parquet"))) == 2
    assert len(control["registros"]) == 1


def test_missing_configured_sheet_fails_before_writing_anything(tmp_path, synthetic_workbook_path, control):
    # Arrange: config con una hoja que no existe en el workbook
    config_con_hoja_faltante = {
        **SHEETS_CONFIG,
        "hoja_fantasma": {"sheet_name": "Hoja Que No Existe", "dest": "fantasma"},
    }
    base_dir = tmp_path / "raw"

    # Act + Assert: falla en la validación fail-fast, mencionando la hoja faltante
    with pytest.raises(ValueError, match="Hoja Que No Existe"):
        pipeline.run_historical_excel_load(
            source_path=synthetic_workbook_path, sheets_config=config_con_hoja_faltante, base_dir=str(base_dir)
        )

    # Assert: no se escribió ningún parquet ni se registró éxito
    assert not base_dir.exists()
    assert control["registros"] == []


def test_failure_on_a_sheet_does_not_register_success(tmp_path, synthetic_workbook_path, control, monkeypatch):
    # Arrange: el guardado de la segunda hoja falla (todo-o-nada)
    llamadas = []

    def guardar_que_falla_en_la_segunda(result, dest_name, base_dir, load_date=None):
        llamadas.append(dest_name)
        if len(llamadas) == 2:
            raise OSError("disco lleno (simulado)")
        return f"{base_dir}/{dest_name}.parquet"

    monkeypatch.setattr(pipeline, "save_extraction_result", guardar_que_falla_en_la_segunda)

    # Act + Assert: el error se propaga
    with pytest.raises(OSError):
        pipeline.run_historical_excel_load(
            source_path=synthetic_workbook_path, sheets_config=SHEETS_CONFIG, base_dir=str(tmp_path / "raw")
        )

    # Assert: no se registró éxito, así la próxima ejecución no queda bloqueada por la guardia
    assert control["registros"] == []
