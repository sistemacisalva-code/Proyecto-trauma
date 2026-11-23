import pandas as pd
import pytest

from etl.transform.common.liquidos import convertir_liquidos
from etl.transform.common.severidad import convertir_severidad

BLOQUE_SEV_EXCEL = "puntuacion_de_severidad_excel"
BLOQUE_LIQ_EXCEL = "liquidos_excel"


class TestSeveridadComun:
    def test_rango_entero_y_regla_del_iss_en_un_bloque_propio(self, reporte, regla):
        """
        Qué es: prueba unitaria de la regla compartida de severidad (common/severidad.py) con un bloque de otra fuente.
        Qué hace: convierte tres filas sintéticas (una coherente, una con el ISS mal sumado y una con una región en 6) en
                  un bloque con nombre propio, como el del Excel.
        Esperado: Int64; la región en 6 queda NA y se cuenta como sobre el máximo; la regla del ISS evalúa 2 filas y 1
                  incumple; la auditoría no tiene pérdidas sin explicar.
        """
        # Arrange: columnas en las que el origen entrega float (como el Excel)
        df = pd.DataFrame({"cabeza": [2.0, 3.0, 6.0], "cara": [0.0] * 3, "torax": [1.0, 2.0, 0.0],
                           "abdomen": [0.0, 1.0, 0.0], "extremidades": [0.0] * 3, "externo": [0.0] * 3,
                           "iss": [5.0, 9.0, 36.0]})

        # Act
        convertir_severidad(df, reporte, BLOQUE_SEV_EXCEL)

        # Assert
        assert str(df["cabeza"].dtype) == str(df["iss"].dtype) == "Int64"
        assert df["cabeza"].isna().tolist() == [False, False, True]
        fila = reporte.auditoria[(BLOQUE_SEV_EXCEL, "cabeza")]
        assert (fila["fuera_de_rango"], fila["sobre_maximo"]) == (1, 1)
        assert regla(BLOQUE_SEV_EXCEL, "iss != suma de cuadrados") == (2, 1)
        reporte.verificar_auditoria()

    def test_region_decimal_detiene_la_ejecucion(self, reporte):
        """
        Qué es: prueba unitaria del contrato entero de severidad.
        Qué hace: convierte una región con 2.5.
        Esperado: ValueError, para decidir qué hacer con el decimal en lugar de redondearlo en silencio.
        """
        # Arrange
        df = pd.DataFrame({"cabeza": [2.5], "cara": [0.0], "torax": [0.0], "abdomen": [0.0], "extremidades": [0.0],
                           "externo": [0.0], "iss": [6.0]})

        # Act + Assert
        with pytest.raises(ValueError):
            convertir_severidad(df, reporte, BLOQUE_SEV_EXCEL)


class TestLiquidosComun:
    def test_limites_duro_y_blando_en_un_bloque_propio(self, reporte, regla):
        """
        Qué es: prueba unitaria de la regla compartida de líquidos (common/liquidos.py) con un bloque de otra fuente.
        Qué hace: convierte tres filas por variable: dentro de rango, sobre el límite blando y sobre el duro (500 L, un
                  posible error de mililitros), más un volumen de 0,01 L.
        Esperado: el volumen de 500 L queda NA y se cuenta; el límite blando solo reporta sin invalidar; el volumen
                  de 0,01 L se reporta como posible error de unidad y se conserva.
        """
        # Arrange: cristaloides con un caso por regla; las otras columnas con un valor normal
        df = pd.DataFrame({"cristaloides": ["2", "15", "500", "0.01"], "coloides": ["0.5"] * 4, "sangre": ["1"] * 4})

        # Act
        convertir_liquidos(df, reporte, BLOQUE_LIQ_EXCEL)

        # Assert
        assert str(df["cristaloides"].dtype) == "Float64"
        assert df["cristaloides"].isna().tolist() == [False, False, True, False]
        assert reporte.auditoria[(BLOQUE_LIQ_EXCEL, "cristaloides")]["sobre_maximo"] == 1
        assert regla(BLOQUE_LIQ_EXCEL, "cristaloides superior a 12.67 L") == (3, 1)
        assert regla(BLOQUE_LIQ_EXCEL, "cristaloides entre 0 y 0.05 L") == (3, 1)
        reporte.verificar_auditoria()
