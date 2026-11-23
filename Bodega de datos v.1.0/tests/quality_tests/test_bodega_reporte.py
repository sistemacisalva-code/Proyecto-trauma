"""
TC-CAL-09: reporte de calidad sobre la bodega cargada con el staging sintético (etl/quality/reporte.py).

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
"""
from datetime import datetime

from etl.quality.reporte import construir_reporte


class TestReporteDeLaBodega:
    def test_tc_cal_09_la_bodega_sintetica_queda_aprobada(self, conexion, contrato):
        """
        Qué es: prueba de calidad del reporte completo sobre la bodega cargada con las dos fuentes sintéticas.
        Qué hace: construye el reporte (verificaciones más bitácora) sobre la base de pruebas.
        Esperado: veredicto Aprobada; las dos cargas exitosas (Excel y REDCap) con su balance por uso; y las seis reglas
                  del módulo en el resumen.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        reporte = construir_reporte(conexion, contrato, ahora=datetime(2026, 10, 27, 20, 30))

        # Assert
        assert reporte.veredicto() == "Aprobada"
        assert sorted(c.fuente for c in reporte.cargas) == ["excel", "redcap"]
        assert {d["carga_id"] for d in reporte.detalle} == {c.id for c in reporte.cargas}
        assert {r.regla for r in reporte.resultados} >= {"QR-INT-01", "QR-DUP-01", "QR-EXA-01", "QR-EXA-03"}

    def test_tc_cal_09_escribe_el_reporte_de_la_ultima_carga(self, conexion, contrato, tmp_path):
        """
        Qué es: prueba de calidad de la escritura del reporte de la bodega sintética.
        Qué hace: construye el reporte y lo escribe en una carpeta temporal.
        Esperado: la carpeta lleva el id de la carga más reciente (REDCap, que se carga después del Excel) y contiene
                  el Markdown y los cuatro CSV.
        """
        # Arrange
        reporte = construir_reporte(conexion, contrato)

        # Act
        carpeta = reporte.escribir(str(tmp_path))

        # Assert
        assert carpeta.name == f"carga_id={max(c.id for c in reporte.cargas)}"
        assert sorted(p.name for p in carpeta.iterdir()) == ["completitud.csv", "reconciliacion.csv", "reglas.csv", "reporte.md",
                                                             "resumen.csv"]
