import pandas as pd

from etl.transform.common.mecanismo import convertir_mecanismo

BLOQUE_EXCEL = "mecanismo_de_lesion_excel"


class TestConvertirMecanismoComun:
    def test_invalida_fuera_de_rango_y_altura_sin_tope(self, reporte):
        """
        Qué es: prueba unitaria de la regla compartida de mecanismo de lesión (common/mecanismo.py).
        Qué hace: convierte scq con un valor sobre 100 y uno negativo, y altura_en_metros con un negativo y una
                  altura muy grande, en un bloque con nombre propio (como el del Excel).
        Esperado: Float64; scq 120 y -1 y altura -2 quedan NA y se cuentan por extremo; la altura de 500 m se
                  conserva (sin tope superior); los decimales se conservan; la auditoría no tiene pérdidas sin explicar.
        """
        # Arrange: datos sintéticos con un caso por límite
        df = pd.DataFrame({"scq": ["4.5", "120", "-1"], "altura_en_metros": ["-2", "500", "1.5"]})

        # Act: convertir con las reglas comunes
        convertir_mecanismo(df, reporte, BLOQUE_EXCEL)

        # Assert: tipos, invalidaciones por extremo y conservación del resto
        assert str(df["scq"].dtype) == str(df["altura_en_metros"].dtype) == "Float64"
        assert df["scq"].isna().tolist() == [False, True, True] and df.loc[0, "scq"] == 4.5
        assert df["altura_en_metros"].isna().tolist() == [True, False, False]
        scq = reporte.auditoria[(BLOQUE_EXCEL, "scq")]
        altura = reporte.auditoria[(BLOQUE_EXCEL, "altura_en_metros")]
        assert (scq["fuera_de_rango"], scq["bajo_minimo"], scq["sobre_maximo"]) == (2, 1, 1)
        assert (altura["fuera_de_rango"], altura["bajo_minimo"], altura["sobre_maximo"]) == (1, 1, 0)
        reporte.verificar_auditoria()

    def test_solo_convierte_las_columnas_presentes(self, reporte):
        """
        Qué es: prueba unitaria de la regla compartida con un bloque parcial.
        Qué hace: convierte un bloque que solo trae scq.
        Esperado: no falla por la columna ausente y solo audita scq.
        """
        # Arrange: bloque sin altura_en_metros
        df = pd.DataFrame({"scq": ["10"]})

        # Act
        convertir_mecanismo(df, reporte, BLOQUE_EXCEL)

        # Assert: una sola variable auditada
        assert list(reporte.auditoria) == [(BLOQUE_EXCEL, "scq")]
