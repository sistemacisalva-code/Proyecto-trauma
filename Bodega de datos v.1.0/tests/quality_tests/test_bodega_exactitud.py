"""
TC-CAL-05, TC-CAL-06 y TC-CAL-07: reglas de exactitud a partir de la bitácora de la carga (QR-EXA-01 y QR-EXA-03) y
verificación del conjunto, sobre la bodega cargada con el staging sintético.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
El defecto se inyecta en la transacción de la prueba y se revierte al terminar. REDCap se carga después del Excel
en el fixture, así que su carga tiene el identificador mayor.
"""
from sqlalchemy import text

from etl.quality.bodega import (
    verificar_bodega, verificar_filas_de_puentes, verificar_reconciliacion,
)
from etl.quality.reporte import estado
from tests.quality_tests.ayudas import por_regla, quitar_restricciones

# Sin lector ni carpeta de reportes, QR-SEG-01 y QR-TRZ-01 no se ejecutan
REGLAS_DEL_MODULO = {"QR-INT-01", "QR-INT-02", "QR-INT-03", "QR-INT-04", "QR-DUP-01", "QR-DUP-02", "QR-EXA-01", "QR-EXA-03", "QR-SEG-02",
                     "QR-TRZ-02", "QR-TRZ-03", "QR-NUL-01", "QR-NUL-04", "QR-NUL-03", "QR-NUL-02", "QR-DOM-01", "QR-DOM-02", "QR-DOM-03", "QR-CON-01",
                     "QR-CON-02", "QR-CON-03", "QR-CON-04", "QR-CON-05", "QR-CON-06", "QR-TIE-01"}


class TestExactitudReconciliacion:
    def test_tc_cal_05_cumple_en_la_bodega_cargada(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-EXA-01 (reconciliación por uso), caso que cumple.
        Que hace: relee de etl_control.carga_detalle el balance de la última carga exitosa de cada fuente.
        Esperado: una verificación por fuente, cada una con usos evaluados y ninguno descuadrado.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_reconciliacion(conexion, contrato)

        # Assert
        assert sorted(r.detalle.split(" ")[0] for r in resultados) == ["excel", "redcap"]
        assert all(r.evaluadas > 0 and r.cumple for r in resultados)

    def test_tc_cal_05_detecta_un_uso_descuadrado(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-EXA-01, caso defectuoso.
        Que hace: quita el CHECK de reconciliación del detalle y suma una fila cargada a un uso de la carga de REDCap.
        Esperado: REDCap reporta 1 uso descuadrado y el Excel, 0.
        """
        # Arrange: el CHECK impediría el defecto; se quita solo en esta transacción
        quitar_restricciones(conexion, "etl_control", "carga_detalle", "c")
        conexion.execute(text(
            "UPDATE etl_control.carga_detalle SET cargadas = cargadas + 1 "
            "WHERE (carga_id, destino, tabla_staging) = (SELECT carga_id, destino, tabla_staging "
            "FROM etl_control.carga_detalle WHERE carga_id = (SELECT max(id) FROM etl_control.carga) LIMIT 1)"))

        # Act
        resultados = verificar_reconciliacion(conexion, contrato)

        # Assert
        (redcap,) = por_regla(resultados, "QR-EXA-01", "redcap")
        (excel,) = por_regla(resultados, "QR-EXA-01", "excel")
        assert (redcap.incumplen, excel.incumplen) == (1, 0)

    def test_tc_cal_05_y_06_sin_cargas_exitosas_no_hay_nada_que_comparar(self, conexion, contrato):
        """
        Que es: prueba de calidad de QR-EXA-01 y QR-EXA-03 cuando la bitácora no tiene cargas.
        Que hace: borra las cargas de etl_control (el detalle cae por ON DELETE CASCADE) y ejecuta las dos verificaciones.
        Esperado: ninguna devuelve resultados; una fuente sin carga exitosa no aparece (no se inventa un cumplimiento).
        """
        # Arrange
        conexion.execute(text("DELETE FROM etl_control.carga"))

        # Act
        reconciliacion = verificar_reconciliacion(conexion, contrato)
        puentes = verificar_filas_de_puentes(conexion, contrato)

        # Assert
        assert reconciliacion == [] and puentes == []


class TestExactitudFilasDePuentes:
    def test_tc_cal_06_cumple_en_la_bodega_cargada(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-EXA-03 (filas de puentes frente a la bitácora), caso que cumple.
        Que hace: compara las filas de cada puente (y rol) y fuente con las cargadas que registró la última carga.
        Esperado: se evalúa el diagnóstico CIE-10 del Excel con filas, y ninguna comparación difiere.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_filas_de_puentes(conexion, contrato)

        # Assert
        (diagnostico,) = por_regla(resultados, "QR-EXA-03", "bridge_atencion_cie_10[diagnostico] (excel)")
        assert diagnostico.evaluadas > 0
        assert all(r.cumple for r in resultados)

    def test_tc_cal_06_detecta_una_fila_borrada_despues_de_la_carga(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-EXA-03, caso defectuoso.
        Que hace: borra una fila de diagnóstico CIE-10 de una atención del Excel, como si alguien la quitara después de
                  la carga.
        Esperado: el diagnóstico del Excel reporta una diferencia de 1 y el de REDCap, 0.
        """
        # Arrange
        conexion.execute(text(
            "DELETE FROM trauma_completo.bridge_atencion_cie_10 WHERE atencion_cie_10_id = "
            "(SELECT b.atencion_cie_10_id FROM trauma_completo.bridge_atencion_cie_10 b "
            "JOIN trauma_completo.fact_trauma f ON f.fact_id = b.fact_id "
            "WHERE b.rol = 'diagnostico' AND f.trauma_register_id LIKE 'EX-%' LIMIT 1)"))

        # Act
        resultados = verificar_filas_de_puentes(conexion, contrato)

        # Assert
        (excel,) = por_regla(resultados, "QR-EXA-03", "bridge_atencion_cie_10[diagnostico] (excel)")
        (redcap,) = por_regla(resultados, "QR-EXA-03", "bridge_atencion_cie_10[diagnostico] (redcap)")
        assert (excel.incumplen, redcap.incumplen) == (1, 0)


class TestVerificacionDelConjunto:
    def test_tc_cal_07_la_bodega_cargada_cumple_todas_las_reglas_del_modulo(self, conexion, contrato):
        """
        Que es: prueba de calidad del conjunto de verificaciones que no necesitan parámetros adicionales.
        Que hace: ejecuta verificar_bodega, sin rol lector ni carpeta de reportes, sobre la bodega cargada con las dos
                  fuentes sintéticas.
        Esperado: aparecen las 25 reglas que no dependen de un rol ni de una carpeta (QR-SEG-01 y QR-TRZ-01 no se
                  ejecutan; QR-TRZ-03 sí, porque lee la ruta de cuarentena de la bitácora) y ninguna falla. Las informativas (vacíos por columna y CIE-10 sin código) sí cuentan filas,
                  porque la bodega sintética tiene una atención vacía y textos sin código a propósito.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_bodega(conexion, contrato)

        # Assert
        assert {r.regla for r in resultados} == REGLAS_DEL_MODULO
        assert [r for r in resultados if estado(r) == "Falla"] == []
