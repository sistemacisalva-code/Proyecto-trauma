import pandas as pd
import pytest

from etl.transform.common.privacy import seudonimizar

CLAVE = "clave-sintetica-de-prueba-0123456789"


class TestPrivacySeudonimizar:
    def test_es_determinista(self):
        """
        Qué es: prueba unitaria de seudonimizar (determinismo).
        Qué hace: seudonimiza dos veces la misma serie sintética con la misma clave.
        Esperado: los resultados son idénticos (condición para detectar pacientes repetidos).
        """
        # Arrange: documentos ficticios
        serie = pd.Series(["CC-1A2B", "CC-3C4D"])

        # Act: dos ejecuciones
        primera = seudonimizar(serie, CLAVE)
        segunda = seudonimizar(serie, CLAVE)

        # Assert: mismo documento, mismo seudónimo
        pd.testing.assert_series_equal(primera, segunda)

    def test_normaliza_formato_antes_de_aplicar_el_hmac(self):
        """
        Qué es: prueba unitaria de la normalización del documento.
        Qué hace: seudonimiza el mismo documento escrito con distinto formato (mayúsculas, guion, espacio, puntos).
        Esperado: todas las variantes producen el mismo seudónimo.
        """
        # Arrange: tres escrituras del mismo documento ficticio y otra equivalente con puntos
        serie = pd.Series(["CC-1A2B", "cc 1a2b", "c.c.1a2b"])

        # Act: seudonimizar
        resultado = seudonimizar(serie, CLAVE)

        # Assert: un solo valor distinto
        assert resultado.nunique() == 1

    def test_documentos_distintos_dan_seudonimos_distintos(self):
        """
        Qué es: prueba unitaria de seudonimizar (no colisión en un caso simple).
        Qué hace: seudonimiza dos documentos ficticios distintos.
        Esperado: dos seudónimos distintos, hexadecimales de 64 caracteres (SHA-256).
        """
        # Arrange: dos documentos distintos
        serie = pd.Series(["CC-1A2B", "CC-3C4D"])

        # Act: seudonimizar
        resultado = seudonimizar(serie, CLAVE)

        # Assert: distintos y con la longitud de un digest SHA-256 en hexadecimal
        assert resultado.nunique() == 2
        assert resultado.str.len().tolist() == [64, 64]
        assert resultado.str.fullmatch(r"[0-9a-f]{64}").all()

    def test_no_contiene_el_documento_original(self):
        """
        Qué es: prueba unitaria de privacidad de seudonimizar.
        Qué hace: seudonimiza un documento ficticio y busca el documento dentro del resultado.
        Esperado: el documento (normalizado o no) no aparece en el seudónimo.
        """
        # Arrange: documento ficticio reconocible
        serie = pd.Series(["CC-9X7Z"])

        # Act: seudonimizar
        resultado = seudonimizar(serie, CLAVE)

        # Assert: sin rastro del identificador
        assert "9x7z" not in resultado.iloc[0].lower()

    def test_otra_clave_produce_otro_seudonimo(self):
        """
        Qué es: prueba unitaria del papel de la clave del HMAC.
        Qué hace: seudonimiza el mismo documento con dos claves distintas.
        Esperado: los seudónimos son distintos (sin la clave no se puede recalcular ni verificar el seudónimo).
        """
        # Arrange: mismo documento y dos claves sintéticas
        serie = pd.Series(["CC-1A2B"])

        # Act: seudonimizar con cada clave
        con_clave_a = seudonimizar(serie, CLAVE)
        con_clave_b = seudonimizar(serie, CLAVE + "-otra")

        # Assert: dependen de la clave
        assert con_clave_a.iloc[0] != con_clave_b.iloc[0]

    def test_clave_en_texto_y_en_bytes_es_equivalente(self):
        """
        Qué es: prueba unitaria del tipo de la clave.
        Qué hace: seudonimiza con la clave como str y como bytes.
        Esperado: el resultado es el mismo.
        """
        # Arrange: un documento y la clave en las dos formas
        serie = pd.Series(["CC-1A2B"])

        # Act: seudonimizar
        con_texto = seudonimizar(serie, CLAVE)
        con_bytes = seudonimizar(serie, CLAVE.encode("utf-8"))

        # Assert: mismo seudónimo
        pd.testing.assert_series_equal(con_texto, con_bytes)

    def test_ausencia_de_identificador_queda_nula(self):
        """
        Qué es: prueba unitaria de seudonimizar ante datos ausentes.
        Qué hace: seudonimiza un nulo, una cadena vacía y un texto sin letras ni dígitos.
        Esperado: las tres posiciones quedan nulas; no se calcula el seudónimo de "nada".
        """
        # Arrange: tres formas de ausencia y un documento válido para conservar el orden
        serie = pd.Series([None, "", "---", "CC-1A2B"])

        # Act: seudonimizar
        resultado = seudonimizar(serie, CLAVE)

        # Assert: nulos donde no hay identificador, valor donde sí lo hay
        assert resultado.isna().tolist() == [True, True, True, False]

    def test_conserva_el_indice_y_no_modifica_la_entrada(self):
        """
        Qué es: prueba unitaria de efectos secundarios de seudonimizar.
        Qué hace: seudonimiza una serie con índice propio y compara la entrada con una copia.
        Esperado: el resultado conserva el índice y el tipo texto; la serie original no cambia.
        """
        # Arrange: índice no consecutivo y copia de referencia
        serie = pd.Series(["CC-1A2B", "CC-3C4D"], index=[10, 20])
        copia = serie.copy()

        # Act: seudonimizar
        resultado = seudonimizar(serie, CLAVE)

        # Assert: mismo índice, tipo texto y entrada intacta
        assert resultado.index.tolist() == [10, 20]
        assert str(resultado.dtype) == "string"
        pd.testing.assert_series_equal(serie, copia)

    @pytest.mark.parametrize("clave", ["", "corta", b"", b"corta"])
    def test_clave_vacia_o_corta_falla(self, clave):
        """
        Qué es: prueba unitaria de la validación de la clave.
        Qué hace: seudonimiza con claves vacías o de menos de 16 bytes, en texto y en bytes (4 casos).
        Esperado: ValueError que menciona PSEUDONYMIZATION_KEY; una clave débil permitiría recuperar el documento.
        """
        # Arrange: serie ficticia
        serie = pd.Series(["CC-1A2B"])

        # Act + Assert: se detiene antes de calcular nada
        with pytest.raises(ValueError, match="PSEUDONYMIZATION_KEY"):
            seudonimizar(serie, clave)
