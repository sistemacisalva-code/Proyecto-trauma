import pandas as pd
import pytest

from etl.transform.common.cronologia import (
    BLOQUE_REPORTE, reportar_eventos_fuera_de_estancia, reportar_reglas_ventilador)


@pytest.fixture
def estancia():
    """
    Llegada y alta sintéticas de tres episodios inventados (A, B, C), indexadas por la llave. C no tiene alta, así que
    sus eventos no son evaluables. Sin datos reales.
    """
    llegada = pd.Series(pd.to_datetime(["2020-01-10 08:00", "2020-02-01 08:00", "2020-03-01 08:00"]),
                        index=["A", "B", "C"])
    alta = pd.Series(pd.to_datetime(["2020-01-15 12:00", "2020-02-03 12:00", None]), index=["A", "B", "C"])
    return llegada, alta


class TestEventosFueraDeEstancia:
    def test_cuenta_antes_y_despues_con_margen(self, estancia, reporte, regla):
        """
        Qué es: prueba unitaria de reportar_eventos_fuera_de_estancia (common/cronologia.py), compartida por REDCap y el
                Excel.
        Qué hace: evalúa 5 signos vitales sintéticos con un margen de 24 h: dentro, dentro del margen tras el alta, antes
                  de la llegada menos el margen, después del alta más el margen y uno del episodio sin alta.
        Esperado: 4 evaluables (el del episodio sin alta no lo es) y 2 fuera de la estancia; la regla queda en el bloque
                  "cronologia" y la tabla no cambia.
        """
        # Arrange
        llegada, alta = estancia
        sv = pd.DataFrame({"llave": ["A", "A", "A", "B", "C"],
                           "fecha": pd.to_datetime(["2020-01-11 10:00", "2020-01-16 06:00", "2020-01-08 07:00",
                                                    "2020-02-05 13:00", "2020-03-02 08:00"])})
        copia = sv.copy()

        # Act
        reportar_eventos_fuera_de_estancia({"sv": sv}, [("sv", "fecha")], llegada, alta, reporte, llave="llave",
                                           margen_horas=24)

        # Assert
        assert regla(BLOQUE_REPORTE, "sv.fecha fuera de la estancia (margen 24 h)") == (4, 2)
        pd.testing.assert_frame_equal(sv, copia)

    def test_sin_margen_por_defecto_los_extremos_cuentan_como_dentro(self, estancia, reporte, regla):
        """
        Qué es: prueba unitaria del margen por defecto de la estancia (0 h desde el 2026-10-31, por indicación del
                personal médico).
        Qué hace: evalúa 4 signos vitales sintéticos del episodio A sin pasar el margen: uno justo en la llegada, uno
                  justo en el alta, uno un minuto después del alta y uno una hora antes de la llegada.
        Esperado: 4 evaluables y 2 fuera de la estancia (los dos que exceden un extremo, por poco); los extremos exactos
                  están dentro; el nombre de la regla indica "margen 0 h".
        """
        # Arrange: episodio A, llegada 2020-01-10 08:00 y alta 2020-01-15 12:00
        llegada, alta = estancia
        sv = pd.DataFrame({"llave": ["A", "A", "A", "A"],
                           "fecha": pd.to_datetime(["2020-01-10 08:00", "2020-01-15 12:00", "2020-01-15 12:01",
                                                    "2020-01-10 07:00"])})

        # Act: sin margen explícito (usa el valor por defecto)
        reportar_eventos_fuera_de_estancia({"sv": sv}, [("sv", "fecha")], llegada, alta, reporte, llave="llave")

        # Assert: solo lo que excede un extremo cuenta como fuera
        assert regla(BLOQUE_REPORTE, "sv.fecha fuera de la estancia (margen 0 h)") == (4, 2)

    def test_llave_repetida_en_el_episodio_detiene(self, reporte):
        """
        Qué es: prueba de la validación del grano del episodio.
        Qué hace: pasa una llegada con la llave repetida.
        Esperado: ValueError (la estancia debe ser una por episodio).
        """
        # Arrange
        llegada = pd.Series(pd.to_datetime(["2020-01-10", "2020-01-11"]), index=["A", "A"])

        # Act + Assert
        with pytest.raises(ValueError, match="una fila por episodio"):
            reportar_eventos_fuera_de_estancia({}, [], llegada, llegada, reporte)


class TestReglasVentilador:
    def test_termino_anterior_y_una_sola_fecha(self, reporte, regla):
        """
        Qué es: prueba unitaria de reportar_reglas_ventilador (common/cronologia.py), usada por el instrumento uci de
                REDCap y la hoja 14 del Excel.
        Qué hace: evalúa 4 filas sintéticas: correcta, término antes del inicio, solo inicio y sin fechas.
        Esperado: término anterior al inicio 2 evaluables y 1 incumple; una sola fecha 3 evaluables y 1 incumple.
        """
        # Arrange
        df = pd.DataFrame({
            "inicio": pd.to_datetime(["2020-01-10 12:00", "2020-01-12 12:00", "2020-01-10 12:00", None]),
            "termino": pd.to_datetime(["2020-01-12 12:00", "2020-01-10 12:00", None, None]),
        })

        # Act
        reportar_reglas_ventilador(df, reporte, "uci", "inicio", "termino")

        # Assert
        assert regla("uci", "termino anterior al inicio") == (2, 1)
        assert regla("uci", "solo una de las dos fechas") == (3, 1)


class TestDetalleDeEventosFueraDeEstancia:
    def test_deja_la_llave_del_episodio_con_eventos_fuera(self, estancia, reporte):
        """
        Qué es: prueba unitaria del detalle de filas de `reportar_eventos_fuera_de_estancia`.
        Qué hace: evalúa signos vitales sintéticos de los episodios A y B, con dos eventos fuera en A y ninguno en B.
        Esperado: detalle_filas guarda solo la llave A, con 2 filas, y el tipo "incumple".
        """
        # Arrange: A tiene dos eventos fuera (uno antes de la llegada y otro después del alta); B, uno dentro
        llegada, alta = estancia
        sv = pd.DataFrame({"llave": ["A", "A", "A", "B"],
                           "fecha": pd.to_datetime(["2020-01-12 10:00", "2020-01-09 08:00", "2020-01-16 08:00",
                                                    "2020-02-02 10:00"])})

        # Act
        reportar_eventos_fuera_de_estancia({"sv": sv}, [("sv", "fecha")], llegada, alta, reporte, llave="llave")

        # Assert
        detalle = reporte.tabla("detalle_filas")
        assert detalle[["llave", "filas", "tipo"]].values.tolist() == [["A", 2, "incumple"]]
