"""
Pruebas del reporte de la transformación en Markdown (`etl/transform/common/reporte_md.py`).

Todo es sintético: reportes armados en memoria con nombres, conteos y llaves inventadas (sin datos clínicos). La prueba
de privacidad usa llaves y valores con un texto reconocible para comprobar que no llegan al archivo.
"""
import pandas as pd

from etl.transform.common.reporte_md import construir_markdown

LLAVE_SECRETA = "LLAVE-SECRETA-123"
VALOR_SECRETO = "VALOR-CLINICO-SECRETO"


def _reporte_con_hallazgos(reporte):
    """
    Completa el `reporte` del fixture con un hallazgo de cada tipo: una regla con casos (con llaves), una sin casos, una
    corrección, una pérdida por conversión, una exclusión, un balance y una atención retirada con su llave. Los valores y
    las llaves son inventados.
    """
    llaves = pd.Series([LLAVE_SECRETA, "otra"])
    reporte.reportar_regla("cronologia", "sv.fecha fuera de la estancia (margen 0 h)", pd.Series([True, True]),
                           pd.Series([True, False]), llaves)
    reporte.reportar_regla("cronologia", "regla sin casos", pd.Series([True, True]), pd.Series([False, False]), llaves)
    reporte.registrar_correccion("procedimientos", "fecha_fin", "regla | con barra", 1, "invalidado (NA)",
                                 llaves, pd.Series([True, False]))
    reporte.registrar_auditoria("signos_vitales", "fc", pd.Series(["60", VALOR_SECRETO]),
                                pd.Series([60, pd.NA], dtype="Int64"), no_convertibles=1)
    reporte.registrar_exclusion("demografia", "nombre", 2, "identificador directo")
    reporte.registrar_balance("hoja_a", 10, "tabla_a", 9)
    reporte.registrar_atenciones_descartadas([{"llave": LLAVE_SECRETA, "conservada": "otra"}])
    return reporte


class TestReporteMarkdown:
    def test_resume_cada_seccion_con_conteos(self, reporte):
        """
        Qué es: prueba unitaria de `construir_markdown`.
        Qué hace: arma el reporte consolidado de una corrida sintética con un hallazgo de cada tipo.
        Esperado: trae el título con la fuente y la corrida, las tablas de salida, el balance, las atenciones retiradas
                  (1), la regla con casos con su porcentaje (50,00 %) y el recuento de las que no marcaron, la corrección,
                  la pérdida por conversión, la exclusión y el número de registros marcados por tipo.
        """
        # Arrange
        _reporte_con_hallazgos(reporte)

        # Act
        md = construir_markdown(reporte, "redcap", "2026-10-31T120000", "2026-10-31T12:00:00+00:00", {"tabla_a": 9})

        # Assert
        assert md.startswith("# Reporte de calidad de la transformación: redcap")
        assert "`2026-10-31T120000`" in md and "| tabla_a | 9 |" in md
        assert "| hoja_a | 10 | tabla_a | 9 |" in md
        assert "1 atenciones retiradas" in md
        assert "1 de 2 reglas marcaron casos; 1 no marcaron ninguno" in md
        assert "| cronologia | sv.fecha fuera de la estancia (margen 0 h) | 2 | 1 | 50.00 % |" in md
        assert "| procedimientos | fecha_fin | regla \\| con barra | invalidado (NA) | 1 |" in md
        assert "| signos_vitales | fc | 1 | 0 | 0 | 0 |" in md
        assert "| demografia | nombre | 2 | identificador directo |" in md
        assert "| corregida | 1 |" in md and "| incumple | 1 |" in md

    def test_no_incluye_llaves_ni_valores(self, reporte):
        """
        Qué es: prueba unitaria de privacidad del reporte en Markdown.
        Qué hace: arma el reporte con llaves y valores reconocibles en las tablas que los contienen.
        Esperado: ni la llave ni el valor aparecen en el texto; solo los conteos y los nombres.
        """
        # Arrange
        _reporte_con_hallazgos(reporte)

        # Act
        md = construir_markdown(reporte, "excel", "2026-10-31T120000", "2026-10-31T12:00:00+00:00", {"tabla_a": 9})

        # Assert
        assert LLAVE_SECRETA not in md and VALOR_SECRETO not in md and "otra" not in md

    def test_un_reporte_vacio_se_escribe_sin_errores(self, reporte):
        """
        Qué es: prueba unitaria del reporte sin hallazgos.
        Qué hace: construye el Markdown de un reporte sin ninguna tabla.
        Esperado: no falla, indica que no hay reglas registradas y 0 atenciones retiradas.
        """
        # Arrange: reporte vacío del fixture

        # Act
        md = construir_markdown(reporte, "excel", "2026-10-31T120000", "2026-10-31T12:00:00+00:00", {})

        # Assert
        assert "No hay reglas registradas." in md and "0 atenciones retiradas" in md
