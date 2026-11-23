"""
TC-CAL-01, TC-CAL-02, TC-CAL-25 y TC-CAL-29: reglas de integridad (QR-INT-01 a QR-INT-04) sobre la bodega cargada con el staging sintético.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Cada regla tiene una prueba del caso que cumple y otra del caso defectuoso: el defecto se inyecta en la transacción de
la prueba (se revierte al terminar) y la verificación debe señalarlo.
"""
from sqlalchemy import text

from etl.quality.bodega import (
    verificar_claves_foraneas, verificar_dimensiones_del_hecho, verificar_huellas, verificar_miembros_por_defecto,
)
from tests.quality_tests.ayudas import (
    ESQUEMA, duplicar_fila, por_regla, quitar_restricciones, restaurar_sin_validar,
)

DIMENSIONES_DEL_HECHO = {
    "paciente_id", "evento_id", "caida_id", "quemadura_id", "accidente_id", "armas_id", "desenlace_id",
    "calificador_signos_id",
}
PRIMERA_ATENCION = "(SELECT min(trauma_register_id) FROM trauma_completo.fact_trauma)"


class TestIntegridadClavesForaneas:
    def test_tc_cal_01_cumple_en_la_bodega_cargada(self, conexion):
        """
        Que es: prueba de calidad de la regla QR-INT-01 (claves foráneas sin huérfanas), caso que cumple.
        Que hace: verifica todas las claves foráneas del esquema sobre la bodega cargada con las dos fuentes sintéticas.
        Esperado: se evalúan filas del hecho hacia una dimensión y de un puente hacia el hecho, y ninguna FK tiene
                  filas huérfanas.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_claves_foraneas(conexion, ESQUEMA)

        # Assert: hay filas evaluadas en las dos clases de FK y ningún incumplimiento
        (hecho,) = por_regla(resultados, "QR-INT-01", "fact_trauma.paciente_id")
        (puente,) = por_regla(resultados, "QR-INT-01", "bridge_atencion_cie_10.fact_id")
        assert hecho.evaluadas > 0 and puente.evaluadas > 0
        assert all(r.cumple for r in resultados)

    def test_tc_cal_01_detecta_un_hecho_sin_su_dimension(self, conexion):
        """
        Que es: prueba de calidad de la regla QR-INT-01, caso defectuoso en el hecho.
        Que hace: quita las claves foráneas del hecho y apunta el paciente de una atención a una fila inexistente.
        Esperado: la FK del paciente reporta 1 fila huérfana y ninguna otra FK incumple.
        """
        # Arrange: la base rechazaría el defecto; se quitan las FK, se inyecta y se restauran como NOT VALID (el
        # verificador las descubre en el catálogo, así que deben seguir existiendo), todo en esta transacción
        quitadas = quitar_restricciones(conexion, ESQUEMA, "fact_trauma", "f")
        conexion.execute(text("UPDATE trauma_completo.fact_trauma SET paciente_id = 999999 "
                              f"WHERE trauma_register_id = {PRIMERA_ATENCION}"))
        restaurar_sin_validar(conexion, ESQUEMA, "fact_trauma", quitadas)

        # Act
        resultados = verificar_claves_foraneas(conexion, ESQUEMA)

        # Assert
        (afectada,) = por_regla(resultados, "QR-INT-01", "fact_trauma.paciente_id")
        assert afectada.incumplen == 1
        assert [r.detalle for r in resultados if r.incumplen] == [afectada.detalle]

    def test_tc_cal_01_detecta_un_puente_sin_hecho(self, conexion):
        """
        Que es: prueba de calidad de la regla QR-INT-01, caso defectuoso en un puente.
        Que hace: quita las claves foráneas del puente de CIE-10 y apunta una de sus filas a un hecho inexistente.
        Esperado: la FK hacia el hecho reporta 1 fila huérfana y ninguna otra FK incumple.
        """
        # Arrange: igual que en el hecho, las FK se restauran como NOT VALID después de inyectar el defecto
        quitadas = quitar_restricciones(conexion, ESQUEMA, "bridge_atencion_cie_10", "f")
        conexion.execute(text(
            "UPDATE trauma_completo.bridge_atencion_cie_10 SET fact_id = 999999 WHERE atencion_cie_10_id = "
            "(SELECT min(atencion_cie_10_id) FROM trauma_completo.bridge_atencion_cie_10)"))
        restaurar_sin_validar(conexion, ESQUEMA, "bridge_atencion_cie_10", quitadas)

        # Act
        resultados = verificar_claves_foraneas(conexion, ESQUEMA)

        # Assert
        (afectada,) = por_regla(resultados, "QR-INT-01", "bridge_atencion_cie_10.fact_id")
        assert afectada.incumplen == 1
        assert [r.detalle for r in resultados if r.incumplen] == [afectada.detalle]


class TestIntegridadDimensionesDelHecho:
    def test_tc_cal_02_cumple_en_la_bodega_cargada(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-INT-02 (FK de dimensión sin NULL, TC-CAR-05), caso que cumple.
        Que hace: cuenta, por cada clave del hecho hacia una dimensión, las filas con la clave en NULL.
        Esperado: se evalúan las 8 claves de dimensión del contrato, cada una con filas, y ninguna tiene NULL: lo
                  vacío apunta a 'Sin dato' o 'No aplica'.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_dimensiones_del_hecho(conexion, contrato)

        # Assert
        assert {r.detalle.split(".")[1] for r in resultados} == DIMENSIONES_DEL_HECHO
        assert all(r.evaluadas > 0 and r.cumple for r in resultados)

    def test_tc_cal_02_detecta_una_clave_de_dimension_nula(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-INT-02, caso defectuoso.
        Que hace: deja en NULL la clave de caída de una atención.
        Esperado: esa clave reporta 1 fila incumplida y las demás 0.
        """
        # Arrange
        conexion.execute(text("UPDATE trauma_completo.fact_trauma SET caida_id = NULL "
                              f"WHERE trauma_register_id = {PRIMERA_ATENCION}"))

        # Act
        resultados = verificar_dimensiones_del_hecho(conexion, contrato)

        # Assert
        (afectada,) = por_regla(resultados, "QR-INT-02", "caida_id")
        assert afectada.incumplen == 1
        assert [r.detalle for r in resultados if r.incumplen] == [afectada.detalle]


class TestIntegridadMiembrosPorDefecto:
    def test_tc_cal_25_cumple_y_detecta_un_miembro_repetido(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-INT-03 (miembros por defecto una sola vez), casos que cumple y defectuoso.
        Que hace: verifica todas las dimensiones y catálogos con miembro por defecto; luego quita las restricciones
                  únicas de dim_evento_trauma y repite su fila 'Sin dato' (todos sus atributos en 'Sin dato').
        Esperado: al inicio, una verificación por tabla (incluidas dim_caida con 'No aplica' y dim_cie_10 con
                  'SIN CODIGO CIE-10') sin incumplimientos; después, solo dim_evento_trauma incumple.
        """
        # Arrange
        inicial = verificar_miembros_por_defecto(conexion, contrato)
        quitar_restricciones(conexion, ESQUEMA, "dim_evento_trauma", "u")
        duplicar_fila(conexion, ESQUEMA, "dim_evento_trauma",
                      "consumo_alcohol = 'Sin dato' AND violencia = 'Sin dato' AND envenenamiento = 'Sin dato' "
                      "AND lugar_evento = 'Sin dato'")

        # Act
        final = verificar_miembros_por_defecto(conexion, contrato)

        # Assert
        assert all(r.cumple for r in inicial)
        assert por_regla(inicial, "QR-INT-03", "dim_caida: miembro 'No aplica'")
        assert por_regla(inicial, "QR-INT-03", "dim_cie_10: miembro 'SIN CODIGO CIE-10'")
        assert [r.detalle for r in final if r.incumplen] == ["dim_evento_trauma: miembro 'Sin dato'"]


class TestIntegridadHuellas:
    def test_tc_cal_29_cumple_y_detecta_una_atencion_sin_huella(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-INT-04 (toda atención tiene huella), casos que cumple y
                defectuoso.
        Que hace: verifica el hecho de la bodega cargada; luego deja en NULL la huella de una atención (la restricción
                  ck_fact_huella admite NULL) y vuelve a verificar.
        Esperado: al inicio, una verificación sobre todas las atenciones con 0 incumplimientos (el Loader escribe la
                  huella en cada una); después, 1 atención sin huella.
        """
        # Arrange
        inicial = verificar_huellas(conexion, contrato)
        conexion.execute(text("UPDATE trauma_completo.fact_trauma SET huella = NULL "
                              f"WHERE trauma_register_id = {PRIMERA_ATENCION}"))

        # Act
        final = verificar_huellas(conexion, contrato)

        # Assert
        (antes,) = por_regla(inicial, "QR-INT-04", "fact_trauma")
        (despues,) = por_regla(final, "QR-INT-04", "fact_trauma")
        assert antes.evaluadas > 0 and antes.cumple
        assert (despues.evaluadas, despues.incumplen) == (antes.evaluadas, 1)
