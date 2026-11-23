import pandas as pd
import pytest

from etl.transform.common.sustancias import cargar_correcciones, estandarizar_sustancias, limpiar_texto_sustancia
from etl.transform.redcap.instrumentos import motivo_de_consulta

BLOQUE = "motivo_de_consulta"
COL_REDCAP = "otras_sustancias_de_abuso"


@pytest.fixture(scope="module")
def catalogo():
    """
    Catálogo real de correcciones (config/catalogos/sustancias_correcciones.yaml). Solo contiene palabras y su
    corrección, sin datos de pacientes; se carga una vez por módulo porque no se modifica.
    """
    return cargar_correcciones()


class TestLimpiarTextoSustancia:
    @pytest.mark.parametrize("valor, esperado", [
        ("marihuna", "MARIHUANA"),
        ("CIGARILLOS", "CIGARRILLOS"),
        ("BAZUCO, PERICO, CLONAZEPA,", "BAZUCO, PERICO, CLONAZEPAM"),
        ("MARIHUANA Y CLONAZEPLAM", "MARIHUANA Y CLONAZEPAM"),
        ("CANABINOIDES", "CANNABINOIDES"),
        ("inhalamtyes y basuco", "INHALANTES Y BAZUCO"),
        ("MARIHUANA  Y TUSI", "MARIHUANA Y TUSSI"),
        ("Heroína", "HEROINA"),
        ("LEÑA", "LEÑA"),
        ("BENZODIACEPINAS", "BENZODIAZEPINAS"),
    ])
    def test_corrige_ortografia(self, catalogo, valor, esperado):
        """
        Qué es: prueba unitaria de limpiar_texto_sustancia (correcciones ortográficas del catálogo compartido).
        Qué hace: limpia textos sintéticos con errores de una palabra, espacios dobles, tildes y coma final.
        Esperado: MAYÚSCULAS, sin tildes (la Ñ se conserva), espacios colapsados y la palabra corregida.
        """
        # Arrange: parámetros sintéticos

        # Act
        resultado = limpiar_texto_sustancia(valor, catalogo)

        # Assert
        assert resultado == esperado

    @pytest.mark.parametrize("valor, esperado", [
        ("niega", "NIEGA"), ("NIEGUA", "NIEGA"), ("ninguna", "NINGUNA"), ("NIGUNO", "NINGUNO"), ("no", "NO"),
        ("PSA", "PSA"), ("XACOL", "XACOL"), ("SACOL", "SACOL"),
        ("1 CIGARRILLO SEMAN", "1 CIGARRILLO SEMAN"),
    ])
    def test_no_unifica_negaciones_ni_grafias_validas(self, catalogo, valor, esperado):
        """
        Qué es: prueba unitaria de lo que la limpieza NO debe hacer (decisiones del usuario, 2026-10-20).
        Qué hace: limpia negaciones, grafías válidas y un texto truncado.
        Esperado: las negaciones conservan su palabra (solo se corrige su ortografía, sin unificar en NINGUNA) y
                  PSA, XACOL, SACOL y SEMAN no se tocan.
        """
        # Arrange: parámetros sintéticos

        # Act
        resultado = limpiar_texto_sustancia(valor, catalogo)

        # Assert
        assert resultado == esperado

    def test_variantes_de_no_especificado_y_solo_signos(self, catalogo):
        """
        Qué es: prueba unitaria de las reglas de valor completo.
        Qué hace: limpia "No especificadas", "desconocida", una frase más larga y un texto de solo signos.
        Esperado: se unifican solo cuando son el valor completo; la frase larga conserva su texto; los signos
                  quedan vacíos.
        """
        # Arrange + Act
        resultados = [limpiar_texto_sustancia(v, catalogo) for v in
                      ["No especificadas", "desconocida", "USO DE SUSTANCIAS NO ESPECIFICADAS", "..."]]

        # Assert
        assert resultados[:3] == ["NO ESPECIFICADO", "DESCONOCIDO", "USO DE SUSTANCIAS NO ESPECIFICADAS"]
        assert pd.isna(resultados[3])


class TestEstandarizarSustancias:
    def test_invalida_fuera_de_dominio_y_audita(self, catalogo, reporte):
        """
        Qué es: prueba unitaria de estandarizar_sustancias (auditoría y correcciones).
        Qué hace: estandariza cinco valores sintéticos: uno con error, uno ya limpio, uno fuera de dominio (un
                  diagnóstico escrito en el campo), uno que se conserva (LEÑA) y un nulo.
        Esperado: el diagnóstico queda NA; la auditoría cuenta 1 no convertible y conserva; se registran 1 fila con
                  texto corregido y 1 invalidada por dominio.
        """
        # Arrange
        df = pd.DataFrame({COL_REDCAP: ["marihuna", "COCAINA", "herida de la pared posterior del torax", "leña",
                                        None]})

        # Act
        estandarizar_sustancias(df, reporte, BLOQUE, COL_REDCAP, catalogo)

        # Assert: valores, auditoría y correcciones
        assert df[COL_REDCAP].tolist()[:2] == ["MARIHUANA", "COCAINA"]
        assert pd.isna(df.loc[2, COL_REDCAP]) and df.loc[3, COL_REDCAP] == "LEÑA" and pd.isna(df.loc[4, COL_REDCAP])
        fila = reporte.auditoria[(BLOQUE, COL_REDCAP)]
        assert (fila["no_nulos_antes"], fila["no_nulos_despues"], fila["no_convertibles"]) == (4, 3, 1)
        assert fila["conserva"]
        filas = {r: v["filas_afectadas"] for (_, _, r), v in reporte.correcciones.items()}
        assert filas["texto estandarizado (mayusculas, sin tildes, errores de escritura)"] == 2
        assert filas["valor que no es una sustancia de abuso (fuera de dominio)"] == 1


class TestInstrumentoMotivoDeConsulta:
    def test_solo_estandariza_otras_sustancias(self, reporte):
        """
        Qué es: prueba unitaria del instrumento motivo_de_consulta de REDCap.
        Qué hace: transforma un bloque sintético con otras_sustancias_de_abuso y otra columna de texto.
        Esperado: solo otras_sustancias_de_abuso cambia (corregida); la otra columna queda igual.
        """
        # Arrange
        df = pd.DataFrame({"record_id": ["1"], "motivo_de_consulta": ["trauma de prueba"],
                           COL_REDCAP: ["clonazepan"]})

        # Act
        resultado = motivo_de_consulta.transformar(df, reporte, {})

        # Assert
        assert resultado.loc[0, COL_REDCAP] == "CLONAZEPAM"
        assert resultado.loc[0, "motivo_de_consulta"] == "trauma de prueba"
        reporte.verificar_auditoria()
