import pandas as pd
import pytest

from etl.transform.common.signos_vitales import convertir_signos_vitales, reportar_reglas_signos_vitales

BLOQUE_EXCEL = "signos_vitales_excel"


@pytest.fixture
def solo_glasgow():
    """
    Bloque sintético con solo las columnas del bloque 5 de registro_trauma del Excel (Glasgow y duración de la
    pérdida de conciencia), sin presiones ni frecuencias. Datos inventados, sin registros reales.
    """
    return pd.DataFrame({
        "traumaregisterrecordid": ["E1", "E2"],
        "gcs_total": ["15", "14"], "gcs_ocular": ["4", "4"], "gcs_verbal": ["5", "5"], "gcs_motora": ["6", "6"],
        "duracion_de_la_perdida_de_conciencia": ["00:10:00", None],
    })


class TestSignosVitalesComunes:
    def test_convierte_solo_las_columnas_presentes(self, solo_glasgow, reporte):
        """
        Qué es: prueba unitaria de convertir_signos_vitales (common) con un bloque parcial.
        Qué hace: convierte un bloque que solo trae el Glasgow y la duración, con el bloque del Excel.
        Esperado: el Glasgow queda Int64, la duración en minutos, no falla por las columnas ausentes y la
                  auditoría queda en el bloque indicado sin pérdidas sin explicar.
        """
        # Arrange: fixture parcial

        # Act: convertir
        convertir_signos_vitales(solo_glasgow, reporte, BLOQUE_EXCEL)

        # Assert: tipos, duración y auditoría en el bloque del Excel
        assert str(solo_glasgow["gcs_total"].dtype) == "Int64"
        assert solo_glasgow["duracion_de_la_perdida_de_conciencia"].iloc[0] == 10.0
        assert (BLOQUE_EXCEL, "gcs_total") in reporte.auditoria
        assert (BLOQUE_EXCEL, "frecuencia_cardiaca") not in reporte.auditoria
        reporte.verificar_auditoria()

    def test_reglas_solo_se_evaluan_con_sus_columnas(self, solo_glasgow, reporte, regla):
        """
        Qué es: prueba unitaria de reportar_reglas_signos_vitales (common) con un bloque parcial.
        Qué hace: evalúa las reglas sobre un bloque sin presiones y con un Glasgow total que no suma (fila 2).
        Esperado: se registra solo la regla del Glasgow (2 evaluables, 1 incumple); la de presiones no se registra.
        """
        # Arrange: tipar primero, como en la transformación
        convertir_signos_vitales(solo_glasgow, reporte, BLOQUE_EXCEL)

        # Act: reportar reglas
        reportar_reglas_signos_vitales(solo_glasgow, reporte, BLOQUE_EXCEL)

        # Assert: solo la regla aplicable
        assert regla(BLOQUE_EXCEL, "gcs_total != ocular + verbal + motora") == (2, 1)
        assert not any("presion" in r for (_, r) in reporte.reglas)

    def test_frecuencia_cardiaca_con_decimal_detiene_la_ejecucion(self, reporte):
        """
        Qué es: prueba unitaria del contrato entero de las frecuencias y presiones (2026-10-19).
        Qué hace: convierte una frecuencia cardiaca de 88.5.
        Esperado: ValueError: un conteo no puede ser decimal; se detiene para decidir cómo tratarlo.
        """
        # Arrange: un decimal en una variable entera
        df = pd.DataFrame({"frecuencia_cardiaca": ["88", "88.5"]})

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="no enteros"):
            convertir_signos_vitales(df, reporte, BLOQUE_EXCEL)

    def test_frecuencia_respiratoria_con_decimal_se_invalida(self, reporte, regla):
        """
        Qué es: prueba unitaria de la excepción al contrato entero para frecuencia_respiratoria (2026-10-22).
        Qué hace: convierte una frecuencia respiratoria sintética de 18.5 junto a una de 20.
        Esperado: no se detiene; el 18.5 queda NA, la regla registra 1 de 2 y la columna sigue siendo Int64.
        """
        # Arrange: un decimal en la única columna entera autorizada a invalidar
        df = pd.DataFrame({"frecuencia_respiratoria": ["18.5", "20"]})

        # Act
        convertir_signos_vitales(df, reporte, BLOQUE_EXCEL)

        # Assert
        assert df["frecuencia_respiratoria"].isna().tolist() == [True, False]
        assert str(df["frecuencia_respiratoria"].dtype) == "Int64"
        assert regla(BLOQUE_EXCEL, "frecuencia_respiratoria con decimal (invalidado)") == (2, 1)
        reporte.verificar_auditoria()
