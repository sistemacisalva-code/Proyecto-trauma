import pandas as pd

from etl.transform.common.laboratorio import (
    convertir_examenes_numericos,
    convertir_sangre_en_orina,
    convertir_tipo_sangre,
)

BLOQUE_EXCEL = "laboratorio_excel"


class TestLaboratorioComun:
    def test_numericos_solo_en_columnas_presentes_y_dispersas(self, reporte):
        """
        Qué es: prueba unitaria de convertir_examenes_numericos (common/laboratorio.py) con la forma del Excel.
        Qué hace: convierte un bloque sintético de una fila por examen, con solo dos variables (hemoglobina y
                  lactato) y cada una informada únicamente en su fila; una hemoglobina fuera del rango duro.
        Esperado: solo se convierten las dos columnas presentes (las demás de REDCap no se exigen); la hemoglobina de
                  40 queda NA y se cuenta sobre el máximo; las celdas de otras filas siguen vacías; la auditoría conserva.
        """
        # Arrange: tres filas, una por examen, como el formato largo del Excel
        lab = pd.DataFrame({"hemoglobina": ["12.5", "40", None], "lactato": [None, None, "2.1"]})

        # Act
        convertir_examenes_numericos(lab, reporte, BLOQUE_EXCEL)

        # Assert
        assert str(lab["hemoglobina"].dtype) == str(lab["lactato"].dtype) == "Float64"
        assert lab["hemoglobina"].isna().tolist() == [False, True, True]
        assert lab["lactato"].isna().tolist() == [True, True, False]
        assert reporte.auditoria[(BLOQUE_EXCEL, "hemoglobina")]["sobre_maximo"] == 1
        assert {c for (_, c) in reporte.auditoria} == {"hemoglobina", "lactato"}
        reporte.verificar_auditoria()

    def test_tipo_de_sangre_y_orina_con_un_bloque_propio(self, reporte):
        """
        Qué es: prueba unitaria de convertir_tipo_sangre y convertir_sangre_en_orina con un bloque de otra fuente.
        Qué hace: normaliza tipos de sangre escritos como en el Excel ("O+", "ab -") y uno ininterpretable, y una
                  sangre en orina con "Negativo", un valor de la escala y un positivo con cruces.
        Esperado: "O+" y "AB-"; el ininterpretable queda NA y se cuenta; "Negativo" pasa a 0, 25 se conserva y el
                  positivo con cruces queda NA como no convertible.
        """
        # Arrange
        df = pd.DataFrame({"tipo_de_sangre_y_factor_rh": ["O+", "ab -", "xyz"],
                           "sangre_en_orina": ["Negativo", "25", "Positivo(+/++/+++)"]})

        # Act
        convertir_tipo_sangre(df, reporte, BLOQUE_EXCEL)
        convertir_sangre_en_orina(df, reporte, BLOQUE_EXCEL)

        # Assert
        assert df["tipo_de_sangre_y_factor_rh"].tolist()[:2] == ["O+", "AB-"]
        assert pd.isna(df.loc[2, "tipo_de_sangre_y_factor_rh"])
        assert df["sangre_en_orina"].tolist()[:2] == [0, 25] and pd.isna(df.loc[2, "sangre_en_orina"])
        assert reporte.auditoria[(BLOQUE_EXCEL, "sangre_en_orina")]["no_convertibles"] == 1
        reporte.verificar_auditoria()
