import pandas as pd
import pytest
from pandas.errors import MergeError

from etl.transform.redcap.cronologia import BLOQUE_REPORTE, verificar_cronologia

LLEGADA_VS_ADMISION = "fecha_y_hora_de_llegada_del_paciente posterior a fecha_de_admision"
LLEGADA_VS_ALTA = "fecha_y_hora_de_llegada_del_paciente posterior a fecha_y_hora_de_alta"
SIGNOS_FUERA = "signos_vitales.fecha_y_hora_de_signos_vitales fuera de la estancia"
SIGNOS_FUTURO = "signos_vitales.fecha_y_hora_de_signos_vitales posterior a la fecha de extraccion"


def _fechas(valores):
    return pd.to_datetime(valores)


@pytest.fixture
def bloques():
    """
    Bloques ya transformados (fechas como datetime) de dos episodios ficticios, todos cronológicamente
    coherentes: llegada <= admisión (por día) <= alta, y todos los eventos dentro de la estancia.
    Fechas inventadas; sin datos clínicos.
    """
    return {
        "informacion_demografica": pd.DataFrame({
            "record_id": ["1", "2"],
            "fecha_y_hora_de_llegada_del_paciente": _fechas(["2024-01-10 08:30", "2024-02-01 20:00"])}),
        "hospitalizacion": pd.DataFrame({
            "record_id": ["1", "2"],
            "fecha_de_admision": _fechas(["2024-01-10", "2024-02-02"]),
            "fecha_y_hora_de_alta": _fechas(["2024-01-15 12:00", "2024-02-03 10:00"])}),
        "signos_vitales": pd.DataFrame({
            "record_id": ["1", "2"],
            "fecha_y_hora_de_signos_vitales": _fechas(["2024-01-10 09:00", "2024-02-01 21:00"])}),
        "laboratorio": pd.DataFrame({
            "record_id": ["1"], "fecha_y_hora_de_laboratorio": _fechas(["2024-01-10 09:30"])}),
        "procedimientos": pd.DataFrame({
            "record_id": ["1"],
            "fecha_y_hora_de_procedimiento": _fechas(["2024-01-10 10:00"]),
            "fecha_y_hora_de_fin_procedimiento": _fechas(["2024-01-10 11:30"])}),
        "uci": pd.DataFrame({
            "record_id": ["1"],
            "fecha_y_hora_de_inicio_del_ventilador": _fechas(["2024-01-10 12:00"]),
            "fecha_y_hora_de_termino_del_ventilador": _fechas(["2024-01-12 12:00"])}),
    }


class TestCronologiaOrdenEntreBloques:
    def test_datos_coherentes_no_incumplen_ninguna_regla(self, bloques, reporte):
        """
        Qué es: prueba unitaria de verificar_cronologia con datos coherentes.
        Qué hace: verifica los bloques sintéticos del fixture con una fecha de extracción posterior a todo.
        Esperado: se registran reglas con filas evaluables y ninguna tiene filas que incumplan.
        """
        # Arrange: bloques coherentes y extracción posterior a todas las fechas
        extraccion = pd.Timestamp("2024-03-01")

        # Act: verificar la cronología
        verificar_cronologia(bloques, reporte, extraccion)

        # Assert: hay reglas evaluadas y ninguna se incumple
        reglas = [v for (b, _), v in reporte.reglas.items() if b == BLOQUE_REPORTE]
        assert sum(v["filas_evaluables"] for v in reglas) > 0
        assert all(v["filas_que_incumplen"] == 0 for v in reglas)

    def test_la_admision_se_compara_por_dia_no_por_hora(self, bloques, reporte, regla):
        """
        Qué es: prueba unitaria de la comparación llegada/admisión.
        Qué hace: usa el episodio 1, que llega a las 08:30 y se admite el mismo día (la admisión no lleva hora).
        Esperado: no es un incumplimiento (2 evaluables, 0 que incumplen): se compara el día, no la hora 00:00.
        """
        # Arrange: bloques coherentes del fixture

        # Act: verificar la cronología
        verificar_cronologia(bloques, reporte)

        # Assert: la llegada del mismo día no se cuenta como posterior a la admisión
        assert regla(BLOQUE_REPORTE, LLEGADA_VS_ADMISION) == (2, 0)

    def test_llegada_posterior_a_la_admision_se_reporta(self, bloques, reporte, regla):
        """
        Qué es: prueba unitaria de la regla llegada posterior a admisión.
        Qué hace: mueve la llegada del episodio 2 al día siguiente de su admisión.
        Esperado: 2 evaluables y 1 que incumple frente a la admisión; frente al alta no incumple (2, 0).
        """
        # Arrange: llegada del episodio 2 el 3 de febrero (la admisión es el 2)
        bloques["informacion_demografica"].loc[1, "fecha_y_hora_de_llegada_del_paciente"] = pd.Timestamp(
            "2024-02-03 08:00")

        # Act: verificar la cronología
        verificar_cronologia(bloques, reporte)

        # Assert: solo la comparación con la admisión se incumple
        assert regla(BLOQUE_REPORTE, LLEGADA_VS_ADMISION) == (2, 1)
        assert regla(BLOQUE_REPORTE, LLEGADA_VS_ALTA) == (2, 0)


class TestCronologiaEventosEnLaEstancia:
    def test_evento_fuera_de_la_estancia_se_reporta_y_no_se_modifica(self, bloques, reporte, regla):
        """
        Qué es: prueba unitaria de la regla de eventos dentro de la estancia.
        Qué hace: mueve unos signos vitales del episodio 1 a más de un mes después del alta.
        Esperado: 2 evaluables y 1 que incumple; la fecha se conserva (solo se reporta).
        """
        # Arrange: signos vitales del episodio 1 en marzo, el alta fue en enero
        fuera = pd.Timestamp("2024-03-01 09:00")
        bloques["signos_vitales"].loc[0, "fecha_y_hora_de_signos_vitales"] = fuera

        # Act: verificar la cronología
        verificar_cronologia(bloques, reporte)

        # Assert: contada como incumplimiento y sin alterar el dato
        assert regla(BLOQUE_REPORTE, SIGNOS_FUERA) == (2, 1)
        assert bloques["signos_vitales"].loc[0, "fecha_y_hora_de_signos_vitales"] == fuera

    @pytest.mark.parametrize("margen_horas, incumplen", [(168, 0), (24, 1)])
    def test_el_margen_de_la_estancia_cambia_el_resultado(self, bloques, reporte, regla, margen_horas, incumplen):
        """
        Qué es: prueba unitaria del margen de tolerancia de la estancia.
        Qué hace: pone unos signos vitales 3 días después del alta y verifica con un margen de 168 h y otro de 24 h.
        Esperado: con 168 h (7 días) no incumple; con 24 h sí (2 casos).
        """
        # Arrange: signos vitales del episodio 1 tres días después del alta (15 de enero 12:00)
        bloques["signos_vitales"].loc[0, "fecha_y_hora_de_signos_vitales"] = pd.Timestamp("2024-01-18 12:00")

        # Act: verificar con el margen parametrizado
        verificar_cronologia(bloques, reporte, margen_horas=margen_horas)

        # Assert: el margen decide si el evento se considera fuera
        assert regla(BLOQUE_REPORTE, SIGNOS_FUERA) == (2, incumplen)

    def test_evento_sin_fecha_no_es_evaluable(self, bloques, reporte, regla):
        """
        Qué es: prueba unitaria de las filas no evaluables.
        Qué hace: deja sin fecha los signos vitales del episodio 2.
        Esperado: solo 1 fila evaluable; un dato ausente no cuenta como incumplimiento.
        """
        # Arrange: una fecha ausente
        bloques["signos_vitales"].loc[1, "fecha_y_hora_de_signos_vitales"] = pd.NaT

        # Act: verificar la cronología
        verificar_cronologia(bloques, reporte)

        # Assert: evaluable solo la que tiene fecha
        assert regla(BLOQUE_REPORTE, SIGNOS_FUERA) == (1, 0)


class TestCronologiaFechasImplausibles:
    def test_fecha_posterior_a_la_extraccion_se_reporta(self, bloques, reporte, regla):
        """
        Qué es: prueba unitaria de la regla de fechas posteriores a la extracción.
        Qué hace: usa como extracción un instante anterior a los signos vitales del episodio 2.
        Esperado: 2 evaluables y 1 que incumple (la referencia es la partición más reciente, no la hora actual).
        """
        # Arrange: extracción el 1 de febrero a las 20:30; los signos del episodio 2 son a las 21:00
        extraccion = pd.Timestamp("2024-02-01 20:30")

        # Act: verificar la cronología
        verificar_cronologia(bloques, reporte, extraccion)

        # Assert: una fecha imposible respecto a la extracción
        assert regla(BLOQUE_REPORTE, SIGNOS_FUTURO) == (2, 1)

    def test_sin_fecha_de_extraccion_no_se_evalua_esa_regla(self, bloques, reporte):
        """
        Qué es: prueba unitaria del comportamiento sin referencia de extracción.
        Qué hace: verifica sin pasar fecha_referencia.
        Esperado: no se registra ninguna regla "posterior a la fecha de extraccion" (no se usa la hora actual).
        """
        # Arrange: bloques coherentes del fixture

        # Act: verificar sin referencia
        verificar_cronologia(bloques, reporte)

        # Assert: ninguna regla depende de la fecha de extracción
        assert not [r for (_, r) in reporte.reglas if "fecha de extraccion" in r]


class TestCronologiaEntrada:
    def test_no_modifica_los_bloques_de_entrada(self, bloques, reporte):
        """
        Qué es: prueba unitaria de que verificar_cronologia solo reporta.
        Qué hace: verifica los bloques y los compara con una copia hecha antes.
        Esperado: todos los bloques quedan idénticos.
        """
        # Arrange: copia de referencia
        copia = {nombre: df.copy() for nombre, df in bloques.items()}

        # Act: verificar la cronología
        verificar_cronologia(bloques, reporte, pd.Timestamp("2024-03-01"))

        # Assert: sin cambios
        for nombre in bloques:
            pd.testing.assert_frame_equal(bloques[nombre], copia[nombre])

    def test_grano_episodio_duplicado_detiene_la_verificacion(self, bloques, reporte):
        """
        Qué es: prueba unitaria de la exigencia de grano episodio en los bloques de la cadena.
        Qué hace: duplica un record_id en hospitalización.
        Esperado: pandas lanza MergeError (relación uno a uno) en lugar de comparar fechas ambiguas.
        """
        # Arrange: el episodio 1 repetido en hospitalización
        bloques["hospitalizacion"] = pd.concat(
            [bloques["hospitalizacion"], bloques["hospitalizacion"].iloc[[0]]], ignore_index=True)

        # Act + Assert: se detiene
        with pytest.raises(MergeError):
            verificar_cronologia(bloques, reporte)
