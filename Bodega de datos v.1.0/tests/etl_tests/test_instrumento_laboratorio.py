import pandas as pd
import pytest

from etl.transform.redcap.instrumentos import laboratorio
from etl.transform.redcap.instrumentos.laboratorio import (
    ESPECIFICACION_NUMERICA,
    RESULTADOS_TOXICOLOGIA,
    normalizar_tipo_sangre,
    transformar,
)

LABORATORIO_BASE = {
    "fecha_y_hora_de_laboratorio": "2024-01-10 09:00",
    "globulos_blancos": "8.5", "hematocrito": "42", "hemoglobina": "14", "plaquetas": "250", "na": "140",
    "k": "4", "cl": "100", "hco3": "24", "bun": "15", "creatinina": "1", "glucosa": "100", "tp": "12",
    "tpt": "30", "inr": "1", "pao2": "90", "paco2": "40", "ph": "7.4", "be": "0", "deficit_de_base": "0",
    "lactato": "1.5",
    "tipo_de_sangre_y_factor_rh": "O+", "sangre_en_orina": "NEG", "anfetaminas": "NEGATIVO",
    "barbituricos": "NEGATIVO", "benzodiacepinas": "NEGATIVO", "cocaina": "NEGATIVO",
    "opiaceos": "NEGATIVO", "fenciclidina": "NEGATIVO", "mioglobinuria": None,  # columna 100 % nula
    "otras_drogas": "MARIHUANA",
}


def _laboratorio(*cambios):
    """DataFrame de laboratorio (texto) con una fila base por cada dict de cambios. Valores inventados."""
    return pd.DataFrame([{"record_id": str(i + 1), **LABORATORIO_BASE, **c} for i, c in enumerate(cambios)])


class TestNormalizarTipoSangre:
    @pytest.mark.parametrize("texto, esperado", [
        ("O+", "O+"), ("o pos", "O+"), ("0 negativo", "O-"), ("AB-", "AB-"), ("A.+", "A+"), ("ab pos", "AB+"),
    ])
    def test_variantes_validas_se_normalizan(self, texto, esperado):
        """
        Qué es: prueba unitaria de normalizar_tipo_sangre (variantes interpretables).
        Qué hace: normaliza seis escrituras de un grupo y factor Rh (mayúsculas, "pos"/"negativo", cero por O, puntos).
        Esperado: el formato canónico ("O+", "O-", "AB-", "A+", "AB+") en cada caso.
        """
        # Arrange: texto parametrizado
        serie = pd.Series([texto])

        # Act: normalizar
        resultado = normalizar_tipo_sangre(serie)

        # Assert: formato canónico
        assert resultado.iloc[0] == esperado

    @pytest.mark.parametrize("texto", ["XYZ", "A", "AB", "5+"])
    def test_lo_no_interpretable_queda_nulo(self, texto):
        """
        Qué es: prueba unitaria de normalizar_tipo_sangre (valores no interpretables).
        Qué hace: normaliza un texto sin grupo, grupos sin Rh y un número con signo (4 casos).
        Esperado: nulo en todos: no se inventa el factor Rh ni el grupo.
        """
        # Arrange: texto parametrizado
        serie = pd.Series([texto])

        # Act: normalizar
        resultado = normalizar_tipo_sangre(serie)

        # Assert: nulo
        assert pd.isna(resultado.iloc[0])


class TestInstrumentoLaboratorio:
    def test_tipos_y_auditoria_con_una_columna_totalmente_nula(self, reporte):
        """
        Qué es: prueba unitaria de laboratorio.transformar (tipado).
        Qué hace: transforma cuatro muestras válidas, con mioglobinuria vacía en todas.
        Esperado: las 20 numéricas del modelo tienen el tipo de ESPECIFICACION_NUMERICA; la toxicología es boolean;
                  otras_drogas es texto; la columna vacía no rompe la guarda ni la auditoría.
        """
        # Arrange: cuatro muestras válidas
        df = _laboratorio({}, {}, {}, {})

        # Act: transformar
        resultado = transformar(df, reporte, {})

        # Assert: tipos por columna
        assert pd.api.types.is_datetime64_any_dtype(resultado["fecha_y_hora_de_laboratorio"])
        for columna, (tipo, _, _) in ESPECIFICACION_NUMERICA.items():
            assert str(resultado[columna].dtype) == tipo, columna
        assert all(str(resultado[c].dtype) == "boolean" for c in RESULTADOS_TOXICOLOGIA)
        assert str(resultado["otras_drogas"].dtype) == "string"
        reporte.verificar_auditoria()

    def test_rango_duro_invalida_pero_rango_plausible_solo_reporta(self, reporte, regla):
        """
        Qué es: prueba unitaria de la diferencia entre invalidar y reportar en laboratorio.
        Qué hace: pone un hematocrito de 200 % (fuera del rango duro) y unos glóbulos blancos de 500 000 (fuera de
                  los rangos plausibles de ambas unidades, sin rango duro porque su unidad sigue sin confirmar).
        Esperado: el hematocrito queda nulo (1 fuera de rango); los glóbulos blancos se conservan y se reportan
                  (1 de 4).
        """
        # Arrange: cuatro muestras, dos con valores atípicos
        df = _laboratorio({}, {"hematocrito": "200"}, {"globulos_blancos": "500000"}, {})

        # Act: transformar
        resultado = transformar(df, reporte, {})

        # Assert: invalidado, conservado y reportado
        assert pd.isna(resultado.loc[1, "hematocrito"])
        assert reporte.auditoria[("laboratorio", "hematocrito")]["fuera_de_rango"] == 1
        assert resultado.loc[2, "globulos_blancos"] == 500000
        assert regla("laboratorio", "globulos_blancos fuera de los rangos plausibles") == (4, 1)

    def test_plaquetas_y_lactato_con_unidad_confirmada_usan_rango_duro(self, reporte):
        """
        Qué es: prueba unitaria del límite duro de plaquetas y lactato tras confirmar su unidad.
        Qué hace: pone unas plaquetas de 2000 (x10^3/uL, fuera de 5-1500) y un lactato de 50 mmol/L (fuera de
                  0.1-30) en dos muestras distintas.
        Esperado: ambos valores quedan nulos y contados en fuera_de_rango (1 cada uno); ya no existe la regla de
                  rango plausible de plaquetas, porque dejaron de ser solo reportadas.
        """
        # Arrange: cuatro muestras, dos con valores imposibles para la unidad confirmada
        df = _laboratorio({}, {"plaquetas": "2000"}, {"lactato": "50"}, {})

        # Act: transformar
        resultado = transformar(df, reporte, {})

        # Assert: invalidados y contados; la regla antigua no se registra
        assert pd.isna(resultado.loc[1, "plaquetas"])
        assert pd.isna(resultado.loc[2, "lactato"])
        assert reporte.auditoria[("laboratorio", "plaquetas")]["fuera_de_rango"] == 1
        assert reporte.auditoria[("laboratorio", "lactato")]["fuera_de_rango"] == 1
        assert not any("plaquetas fuera de los rangos plausibles" in r for (_, r) in reporte.reglas)

    def test_sangre_en_orina_unifica_negativos_y_cuenta_el_texto_ajeno(self, reporte):
        """
        Qué es: prueba unitaria de la doble transformación de sangre_en_orina (decisión 2.17).
        Qué hace: transforma "neg", "NEGATIVO", "50" y un texto no correspondiente.
        Esperado: los negativos pasan a 0, el 50 se conserva, el texto ajeno queda nulo y contado
                  como no convertible (1); la columna es Int64.
        """
        # Arrange: cuatro valores de la columna
        df = _laboratorio({"sangre_en_orina": "neg"}, {"sangre_en_orina": "NEGATIVO"},
                          {"sangre_en_orina": "50"}, {"sangre_en_orina": "no se hizo"})

        # Act: transformar
        resultado = transformar(df, reporte, {})

        # Assert: valores, tipo y conteo
        assert resultado["sangre_en_orina"].tolist()[:3] == [0, 0, 50]
        assert pd.isna(resultado.loc[3, "sangre_en_orina"])
        assert str(resultado["sangre_en_orina"].dtype) == "Int64"
        assert reporte.auditoria[("laboratorio", "sangre_en_orina")]["no_convertibles"] == 1

    def test_tipo_de_sangre_no_interpretable_se_cuenta(self, reporte):
        """
        Qué es: prueba unitaria de la auditoría del tipo de sangre.
        Qué hace: transforma tres tipos válidos y uno ilegible.
        Esperado: el ilegible queda nulo y se cuenta como no convertible (1), sin pérdidas sin explicar.
        """
        # Arrange: tres válidos y uno ilegible
        df = _laboratorio({"tipo_de_sangre_y_factor_rh": "O pos"}, {"tipo_de_sangre_y_factor_rh": "A-"},
                          {"tipo_de_sangre_y_factor_rh": "B+"}, {"tipo_de_sangre_y_factor_rh": "???"})

        # Act: transformar
        resultado = transformar(df, reporte, {})

        # Assert: normalizados, nulo y contado
        assert resultado["tipo_de_sangre_y_factor_rh"].tolist()[:3] == ["O+", "A-", "B+"]
        assert pd.isna(resultado.loc[3, "tipo_de_sangre_y_factor_rh"])
        assert reporte.auditoria[("laboratorio", "tipo_de_sangre_y_factor_rh")]["no_convertibles"] == 1
        reporte.verificar_auditoria()

    def test_toxicologia_no_imputa_la_celda_vacia_como_negativa(self, reporte):
        """
        Qué es: prueba unitaria de la toxicología de dominio cerrado (decisión 2.22).
        Qué hace: transforma cocaína con "POSITIVO", "NEGATIVO", vacío y otro "NEGATIVO".
        Esperado: True, False, nulo y False: una celda vacía significa que el examen no se registró.
        """
        # Arrange: cuatro resultados de cocaína
        df = _laboratorio({"cocaina": "POSITIVO"}, {"cocaina": "NEGATIVO"}, {"cocaina": None}, {})

        # Act: transformar
        resultado = transformar(df, reporte, {})

        # Assert: dominio cerrado y vacío sin imputar
        assert resultado["cocaina"].isna().tolist() == [False, False, True, False]
        assert resultado["cocaina"].iloc[[0, 1, 3]].tolist() == [True, False, False]

    def test_reglas_de_consistencia_solo_se_reportan(self, reporte, regla):
        """
        Qué es: prueba unitaria de las reglas de consistencia de laboratorio.
        Qué hace: pone un hematocrito de 60 con hemoglobina de 10 (relación 6, fuera de [2.5, 3.5]) y una celda de
                  otras_drogas con dos sustancias.
        Esperado: la regla de los tres incumple en 1 de 4; la de multivalor, en 1 de 4; los valores se conservan.
        """
        # Arrange: cuatro muestras, dos con incoherencias
        df = _laboratorio({}, {"hematocrito": "60", "hemoglobina": "10"},
                          {"otras_drogas": "MARIHUANA, ALCOHOL"}, {})

        # Act: transformar
        resultado = transformar(df, reporte, {})

        # Assert: contadas y conservadas
        assert regla("laboratorio", "hematocrito / hemoglobina fuera de [2.5, 3.5]") == (4, 1)
        assert regla("laboratorio", "otras_drogas con varias sustancias") == (4, 1)
        assert resultado.loc[1, "hematocrito"] == 60
        assert resultado.loc[2, "otras_drogas"] == "MARIHUANA, ALCOHOL"

    def test_contrato_del_modulo(self):
        """
        Qué es: prueba del contrato de instrumento del módulo de laboratorio.
        Qué hace: revisa NOMBRE y las categóricas declaradas.
        Esperado: NOMBRE es "laboratorio"; las categóricas son los 7 resultados de toxicología y el tipo de sangre.
        """
        # Arrange: el módulo importado

        # Act: no aplica, se inspeccionan sus constantes

        # Assert: contrato
        assert laboratorio.NOMBRE == "laboratorio"
        assert set(laboratorio.CATEGORICAS) == set(RESULTADOS_TOXICOLOGIA) | {"tipo_de_sangre_y_factor_rh"}
