"""
TC-CAL-10 y TC-CAL-11: reglas de seguridad (QR-SEG-01 y QR-SEG-02) sobre la bodega cargada con el staging sintético.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Los defectos (un permiso de más, una columna con nombre de identificación) se inyectan en la transacción de la prueba,
que se revierte al terminar. El rol lector es el de la base de pruebas.
"""
from sqlalchemy import text

from etl.quality.bodega import (
    COLUMNAS_RESERVADAS, verificar_columnas_identificadoras, verificar_permisos_del_lector,
)
from tests.quality_tests.ayudas import por_regla


class TestSeguridadPermisosDelLector:
    def test_tc_cal_10_cumple_en_la_bodega_cargada(self, conexion, contrato, bd_prueba):
        """
        Que es: prueba de calidad de la regla QR-SEG-01 (permisos del lector), caso que cumple.
        Que hace: consulta los privilegios efectivos del rol lector sobre las columnas reservadas y sobre las tablas.
        Esperado: el lector no puede leer ninguna de las cinco columnas reservadas (cuatro de texto libre y la huella
                  de la carga) y no puede modificar ninguna tabla del esquema.
        """
        # Arrange: permisos aplicados por main.py al crear la base de pruebas

        # Act
        resultados = verificar_permisos_del_lector(conexion, contrato, bd_prueba["reader"])

        # Assert
        (reservadas,) = por_regla(resultados, "QR-SEG-01", "columnas reservadas")
        (solo_lectura,) = por_regla(resultados, "QR-SEG-01", "solo con lectura")
        assert reservadas.evaluadas == len(COLUMNAS_RESERVADAS) == 5 and reservadas.cumple
        assert solo_lectura.evaluadas > 0 and solo_lectura.cumple

    def test_tc_cal_10_detecta_una_columna_reservada_legible(self, conexion, contrato, bd_prueba):
        """
        Que es: prueba de calidad de la regla QR-SEG-01, caso defectuoso de lectura.
        Que hace: concede al lector SELECT sobre texto_origen del puente de CIE-10.
        Esperado: la verificación de columnas reservadas reporta 1 columna legible y la de solo lectura, 0.
        """
        # Arrange
        lector = bd_prueba["reader"]
        conexion.execute(text(f"GRANT SELECT (texto_origen) ON trauma_completo.bridge_atencion_cie_10 TO {lector}"))

        # Act
        resultados = verificar_permisos_del_lector(conexion, contrato, lector)

        # Assert
        (reservadas,) = por_regla(resultados, "QR-SEG-01", "columnas reservadas")
        (solo_lectura,) = por_regla(resultados, "QR-SEG-01", "solo con lectura")
        assert (reservadas.incumplen, solo_lectura.incumplen) == (1, 0)

    def test_tc_cal_10_detecta_un_permiso_de_escritura(self, conexion, contrato, bd_prueba):
        """
        Que es: prueba de calidad de la regla QR-SEG-01, caso defectuoso de escritura.
        Que hace: concede al lector INSERT sobre la dimensión de caída.
        Esperado: la verificación de solo lectura reporta 1 tabla modificable y la de columnas reservadas, 0.
        """
        # Arrange
        lector = bd_prueba["reader"]
        conexion.execute(text(f"GRANT INSERT ON trauma_completo.dim_caida TO {lector}"))

        # Act
        resultados = verificar_permisos_del_lector(conexion, contrato, lector)

        # Assert
        (reservadas,) = por_regla(resultados, "QR-SEG-01", "columnas reservadas")
        (solo_lectura,) = por_regla(resultados, "QR-SEG-01", "solo con lectura")
        assert (reservadas.incumplen, solo_lectura.incumplen) == (0, 1)


class TestSeguridadColumnasIdentificadoras:
    def test_tc_cal_11_cumple_en_la_bodega_cargada(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-SEG-02 (sin columnas de identificación), caso que cumple.
        Que hace: revisa los nombres de todas las columnas del esquema contra el patrón de identificación.
        Esperado: se evalúan las columnas del esquema y ninguna lleva un nombre de documento, nombre, teléfono, etc.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        (resultado,) = verificar_columnas_identificadoras(conexion, contrato)

        # Assert
        assert resultado.regla == "QR-SEG-02" and resultado.evaluadas > 0 and resultado.cumple

    def test_tc_cal_11_detecta_una_columna_con_nombre_de_identificacion(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-SEG-02, caso defectuoso.
        Que hace: agrega a la dimensión de caída una columna llamada documento_paciente.
        Esperado: la verificación reporta 1 columna con nombre de identificación.
        """
        # Arrange
        conexion.execute(text("ALTER TABLE trauma_completo.dim_caida ADD COLUMN documento_paciente TEXT"))

        # Act
        (resultado,) = verificar_columnas_identificadoras(conexion, contrato)

        # Assert
        assert resultado.incumplen == 1
