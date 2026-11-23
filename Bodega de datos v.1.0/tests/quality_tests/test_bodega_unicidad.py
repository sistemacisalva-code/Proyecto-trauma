"""
TC-CAL-03 y TC-CAL-04: reglas de unicidad (QR-DUP-01 y QR-DUP-02) sobre la bodega cargada con el staging sintético.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
El defecto se inyecta en la transacción de la prueba, quitando antes la restricción UNIQUE que lo impediría; la
transacción se revierte al terminar.
"""
from sqlalchemy import text

from etl.quality.bodega import verificar_atenciones, verificar_filas_repetidas
from tests.quality_tests.ayudas import ESQUEMA, duplicar_fila, por_regla, quitar_restricciones

PRIMERA_ATENCION = "(SELECT min(trauma_register_id) FROM trauma_completo.fact_trauma)"
TIPOS_REPETIBLES = ("dimension", "catalogo", "puente")


class TestUnicidadAtenciones:
    def test_tc_cal_03_cumple_en_la_bodega_cargada(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-DUP-01 (llave de atención única y con prefijo), caso que cumple.
        Que hace: cuenta las llaves repetidas y las que no empiezan por EX- ni RC- en el hecho cargado.
        Esperado: dos verificaciones (repetidas y prefijo) sobre las mismas atenciones, con 0 incumplimientos.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_atenciones(conexion, contrato)

        # Assert
        assert len(resultados) == 2
        assert all(r.evaluadas > 0 and r.cumple for r in resultados)

    def test_tc_cal_03_detecta_una_llave_repetida(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-DUP-01, caso defectuoso por repetición.
        Que hace: quita el UNIQUE del hecho y duplica una atención.
        Esperado: la verificación de repetidas reporta 1 fila sobrante y la del prefijo, 0.
        """
        # Arrange
        quitar_restricciones(conexion, ESQUEMA, "fact_trauma", "u")
        duplicar_fila(conexion, ESQUEMA, "fact_trauma", f"trauma_register_id = {PRIMERA_ATENCION}")

        # Act
        resultados = verificar_atenciones(conexion, contrato)

        # Assert
        (repetidas,) = por_regla(resultados, "QR-DUP-01", "sin repetir")
        (prefijo,) = por_regla(resultados, "QR-DUP-01", "prefijo")
        assert (repetidas.incumplen, prefijo.incumplen) == (1, 0)

    def test_tc_cal_03_detecta_una_llave_sin_prefijo_de_fuente(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-DUP-01, caso defectuoso por prefijo.
        Que hace: cambia la llave de una atención por una que no empieza por EX- ni RC-.
        Esperado: la verificación del prefijo reporta 1 fila y la de repetidas, 0 (sin ese prefijo el reemplazo por
                  fuente no la encontraría).
        """
        # Arrange
        conexion.execute(text("UPDATE trauma_completo.fact_trauma SET trauma_register_id = 'ZZ-1' "
                              f"WHERE trauma_register_id = {PRIMERA_ATENCION}"))

        # Act
        resultados = verificar_atenciones(conexion, contrato)

        # Assert
        (repetidas,) = por_regla(resultados, "QR-DUP-01", "sin repetir")
        (prefijo,) = por_regla(resultados, "QR-DUP-01", "prefijo")
        assert (repetidas.incumplen, prefijo.incumplen) == (0, 1)


class TestUnicidadFilasRepetidas:
    def test_tc_cal_04_cumple_en_la_bodega_cargada(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-DUP-02 (sin filas repetidas), caso que cumple.
        Que hace: agrupa por todas las columnas, salvo la clave sustituta, cada dimensión, catálogo y puente.
        Esperado: se evalúan todas las tablas de esos tipos del contrato, la dimensión de caída con filas, y ninguna
                  tiene filas sobrantes.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_filas_repetidas(conexion, contrato)

        # Assert
        esperadas = {t for t, d in contrato.tablas.items() if d["tipo"] in TIPOS_REPETIBLES}
        assert {r.detalle for r in resultados} == esperadas
        (caida,) = por_regla(resultados, "QR-DUP-02", "dim_caida")
        assert caida.evaluadas > 0
        assert all(r.cumple for r in resultados)

    def test_tc_cal_04_detecta_una_combinacion_repetida_en_una_dimension(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-DUP-02, caso defectuoso en una dimensión.
        Que hace: quita el UNIQUE de la dimensión de caída y duplica una de sus filas (la base le da otra clave).
        Esperado: esa dimensión reporta 1 fila sobrante y ninguna otra tabla incumple.
        """
        # Arrange
        quitar_restricciones(conexion, ESQUEMA, "dim_caida", "u")
        duplicar_fila(conexion, ESQUEMA, "dim_caida",
                      "caida_id = (SELECT min(caida_id) FROM trauma_completo.dim_caida)")

        # Act
        resultados = verificar_filas_repetidas(conexion, contrato)

        # Assert
        (afectada,) = por_regla(resultados, "QR-DUP-02", "dim_caida")
        assert afectada.incumplen == 1
        assert [r.detalle for r in resultados if r.incumplen] == [afectada.detalle]

    def test_tc_cal_04_detecta_una_fila_repetida_en_un_puente(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-DUP-02, caso defectuoso en un puente.
        Que hace: quita el UNIQUE del puente de CIE-10 y duplica una de sus filas (la base le da otra clave).
        Esperado: el puente reporta 1 fila sobrante y ninguna otra tabla incumple.
        """
        # Arrange
        quitar_restricciones(conexion, ESQUEMA, "bridge_atencion_cie_10", "u")
        duplicar_fila(conexion, ESQUEMA, "bridge_atencion_cie_10",
                      "atencion_cie_10_id = (SELECT min(atencion_cie_10_id) FROM trauma_completo.bridge_atencion_cie_10)")

        # Act
        resultados = verificar_filas_repetidas(conexion, contrato)

        # Assert
        (afectada,) = por_regla(resultados, "QR-DUP-02", "bridge_atencion_cie_10")
        assert afectada.incumplen == 1
        assert [r.detalle for r in resultados if r.incumplen] == [afectada.detalle]
