import pandas as pd
import pytest

from etl.transform.redcap.instrumentos import liquidos, puntuacion_de_severidad, signos_vitales

SIGNOS_BASE = {
    "fecha_y_hora_de_signos_vitales": "2024-01-10 08:45", "frecuencia_cardiaca": "88",
    "presion_arterial_sistolica": "120", "presion_arterial_diastolica": "80",
    "frecuencia_respiratoria": "18", "saturacion_de_oxigeno": "97", "temperatura": "36.5",
    "peso": "70", "altura": "1.7", "gcs_total": "15", "gcs_ocular": "4", "gcs_verbal": "5",
    "gcs_motora": "6", "duracion_de_la_perdida_de_conciencia": "00:10:00",
}


def _signos(*cambios):
    """Un DataFrame de signos vitales (texto) con una fila base por cada dict de cambios."""
    filas = [{"record_id": str(i + 1), **SIGNOS_BASE, **c} for i, c in enumerate(cambios)]
    return pd.DataFrame(filas)


class TestInstrumentoSignosVitales:
    def test_tipos_segun_el_modelo(self, reporte):
        """
        Qué es: prueba unitaria de signos_vitales.transformar (tipado).
        Qué hace: transforma tres tomas sintéticas válidas.
        Esperado: fecha datetime; frecuencias, presiones y componentes del Glasgow Int64 (conteos enteros);
                  temperatura, saturación, peso y altura Float64; la pérdida de conciencia "00:10:00" pasa a
                  10 minutos; auditoría sin pérdidas sin explicar.
        """
        # Arrange: tres filas válidas
        df = _signos({}, {}, {})

        # Act: transformar
        resultado = signos_vitales.transformar(df, reporte, {})

        # Assert: tipos y conversión de la duración
        assert pd.api.types.is_datetime64_any_dtype(resultado["fecha_y_hora_de_signos_vitales"])
        enteras = ["frecuencia_cardiaca", "presion_arterial_sistolica", "presion_arterial_diastolica",
                   "frecuencia_respiratoria", "gcs_total", "gcs_motora"]
        assert all(str(resultado[c].dtype) == "Int64" for c in enteras)
        assert str(resultado["temperatura"].dtype) == str(resultado["peso"].dtype) == "Float64"
        assert resultado["duracion_de_la_perdida_de_conciencia"].iloc[0] == 10.0
        reporte.verificar_auditoria()

    @pytest.mark.parametrize("columna, valor", [
        ("temperatura", "98.6"),      # grados Fahrenheit: fuera de [25, 45]
        ("altura", "170"),            # centímetros: fuera de [0.3, 2.5]
        ("saturacion_de_oxigeno", "150"),
    ])
    def test_valor_fuera_de_rango_se_invalida_y_se_cuenta(self, columna, valor, reporte):
        """
        Qué es: prueba unitaria de los rangos de plausibilidad de signos_vitales.
        Qué hace: pone un valor en otra unidad o imposible en una de tres tomas (3 casos: temperatura en °F,
                  altura en cm y saturación mayor de 100).
        Esperado: el valor queda nulo, la auditoría cuenta 1 fuera de rango y las otras dos tomas se conservan.
        """
        # Arrange: la segunda toma lleva el valor atípico
        df = _signos({}, {columna: valor}, {})

        # Act: transformar
        resultado = signos_vitales.transformar(df, reporte, {})

        # Assert: invalidado y contado, el resto intacto
        assert resultado[columna].isna().tolist() == [False, True, False]
        assert reporte.auditoria[("signos_vitales", columna)]["fuera_de_rango"] == 1
        reporte.verificar_auditoria()

    def test_perdida_de_conciencia_de_mas_de_24_horas_se_invalida(self, reporte):
        """
        Qué es: prueba unitaria del límite de la pérdida de conciencia (24 h, propuesta por validar).
        Qué hace: pone una duración de 30 horas en una de tres tomas.
        Esperado: queda nula y la auditoría cuenta 1 fuera de rango.
        """
        # Arrange: duración de 30 horas
        df = _signos({}, {"duracion_de_la_perdida_de_conciencia": "30:00:00"}, {})

        # Act: transformar
        resultado = signos_vitales.transformar(df, reporte, {})

        # Assert: invalidada y contada
        assert resultado["duracion_de_la_perdida_de_conciencia"].isna().tolist() == [False, True, False]
        assert reporte.auditoria[("signos_vitales", "duracion_de_la_perdida_de_conciencia")]["fuera_de_rango"] == 1

    def test_reglas_de_consistencia_solo_se_reportan(self, reporte, regla):
        """
        Qué es: prueba unitaria de las dos reglas de consistencia de signos_vitales.
        Qué hace: pone una diastólica mayor que la sistólica en la toma 2 y un Glasgow total que no suma
                  sus componentes en la toma 3.
        Esperado: cada regla incumple en 1 de 3 filas evaluables y los valores no se modifican.
        """
        # Arrange: dos incoherencias en filas distintas
        df = _signos({}, {"presion_arterial_diastolica": "130"}, {"gcs_total": "14"})

        # Act: transformar
        resultado = signos_vitales.transformar(df, reporte, {})

        # Assert: contadas y conservadas
        assert regla("signos_vitales", "presion diastolica > sistolica") == (3, 1)
        assert regla("signos_vitales", "gcs_total != ocular + verbal + motora") == (3, 1)
        assert resultado.loc[1, "presion_arterial_diastolica"] == 130
        assert resultado.loc[2, "gcs_total"] == 14


class TestInstrumentoPuntuacionDeSeveridad:
    REGIONES = ["cabeza", "cara", "torax", "abdomen", "extremidades", "externo"]

    def _severidad(self, *filas):
        """DataFrame de severidad (texto): cada fila es (cabeza, cara, torax, abdomen, extremidades, externo, iss)."""
        columnas = self.REGIONES + ["iss"]
        return pd.DataFrame([dict(zip(columnas, map(str, f)), record_id=str(i + 1))
                             for i, f in enumerate(filas)])

    def test_tipos_y_regla_del_iss(self, reporte, regla):
        """
        Qué es: prueba unitaria de puntuacion_de_severidad.transformar (tipado y regla del ISS).
        Qué hace: transforma tres filas: ISS correcto (2² + 1² = 5), ISS correcto (3² + 2² + 1² = 14) y
                  un ISS de 9 cuando las regiones suman 5.
        Esperado: todas las columnas Int64; la regla evalúa 3 filas y 1 incumple; el ISS erróneo no se corrige.
        """
        # Arrange: tres filas con las seis regiones y el ISS
        df = self._severidad((2, 0, 1, 0, 0, 0, 5), (3, 0, 2, 1, 0, 0, 14), (2, 0, 1, 0, 0, 0, 9))

        # Act: transformar
        resultado = puntuacion_de_severidad.transformar(df, reporte, {})

        # Assert: tipos, regla y valor conservado
        assert all(str(resultado[c].dtype) == "Int64" for c in self.REGIONES + ["iss"])
        assert regla("puntuacion_de_severidad", "iss != suma de cuadrados") == (3, 1)
        assert resultado.loc[2, "iss"] == 9
        reporte.verificar_auditoria()

    def test_ais_fuera_de_0_a_5_se_invalida_y_queda_fuera_de_la_regla(self, reporte, regla):
        """
        Qué es: prueba unitaria del dominio del AIS [0, 5] (AIS 6 sin confirmar).
        Qué hace: pone un 6 en la cabeza de una de tres filas.
        Esperado: ese valor queda nulo (1 fuera de rango) y la fila deja de ser evaluable en la regla del ISS.
        """
        # Arrange: la fila 3 tiene un AIS de 6
        df = self._severidad((2, 0, 1, 0, 0, 0, 5), (3, 0, 2, 1, 0, 0, 14), (6, 0, 0, 0, 0, 0, 36))

        # Act: transformar
        resultado = puntuacion_de_severidad.transformar(df, reporte, {})

        # Assert: invalidado, contado y fila no evaluable
        assert pd.isna(resultado.loc[2, "cabeza"])
        assert reporte.auditoria[("puntuacion_de_severidad", "cabeza")]["fuera_de_rango"] == 1
        assert regla("puntuacion_de_severidad", "iss != suma de cuadrados") == (2, 0)

    def test_region_decimal_detiene_la_ejecucion(self, reporte):
        """
        Qué es: prueba unitaria del contrato entero de las regiones.
        Qué hace: pone un AIS de 2.5.
        Esperado: ValueError que menciona "enteros".
        """
        # Arrange: AIS decimal
        df = self._severidad((2.5, 0, 1, 0, 0, 0, 5))

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="enteros"):
            puntuacion_de_severidad.transformar(df, reporte, {})


class TestInstrumentoLiquidos:
    @pytest.fixture
    def volumenes(self):
        """
        Bloque de líquidos sintético de cuatro filas (texto), en litros. Cristaloides: valor normal (1.5),
        extremo pero posible (15), en mililitros por error (500) y posible error de unidad (0.001).
        """
        return pd.DataFrame({
            "record_id": ["1", "2", "3", "4"],
            "cristaloides": ["1.5", "15", "500", "0.001"],
            "coloides": ["0.5", "0.5", "0.5", "0.5"],
            "sangre": ["1", "1", "1", "1"],
        })

    def test_limite_duro_invalida_y_limite_blando_solo_reporta(self, volumenes, reporte, regla):
        """
        Qué es: prueba unitaria de los límites duro y blando de liquidos (decisión 2.20).
        Qué hace: transforma el bloque sintético.
        Esperado: los 500 L (error de unidad) se invalidan y se cuentan fuera de rango; los 15 L superan el límite
                  blando (12.67) pero se conservan y se reportan (1 de 3 evaluables).
        """
        # Arrange: bloque del fixture

        # Act: transformar
        resultado = liquidos.transformar(volumenes, reporte, {})

        # Assert: duro invalida, blando conserva
        assert pd.isna(resultado.loc[2, "cristaloides"])
        assert resultado.loc[1, "cristaloides"] == 15
        assert reporte.auditoria[("liquidos", "cristaloides")]["fuera_de_rango"] == 1
        assert regla("liquidos", "cristaloides superior a 12.67 L") == (3, 1)
        reporte.verificar_auditoria()

    def test_volumen_diminuto_se_reporta_como_posible_error_de_unidad(self, volumenes, reporte, regla):
        """
        Qué es: prueba unitaria de la regla de posible error de unidad en liquidos.
        Qué hace: transforma el bloque sintético, con 0.001 L de cristaloides.
        Esperado: 1 de 3 evaluables entre 0 y 0.05 L; el valor se conserva (solo se reporta).
        """
        # Arrange: bloque del fixture

        # Act: transformar
        resultado = liquidos.transformar(volumenes, reporte, {})

        # Assert: contado y conservado
        assert regla("liquidos", "cristaloides entre 0 y 0.05 L") == (3, 1)
        assert resultado.loc[3, "cristaloides"] == 0.001
