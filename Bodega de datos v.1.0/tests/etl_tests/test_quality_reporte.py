"""
TC-CAL-08: reporte de calidad de la bodega cargada (etl/quality/reporte.py), sin base de datos.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Los resultados, las cargas y el balance por uso se construyen a mano con valores inventados: no hay datos reales y
el reporte solo lleva conteos.
"""
import csv
from datetime import datetime

import pytest

from etl.quality.bodega import Resultado
from etl.quality.reporte import Carga, Reporte

AHORA = datetime(2026, 10, 27, 20, 30)


def _carga(id: int, fuente: str) -> Carga:
    return Carga(id=id, fuente=fuente, run_id_staging="2026-10-27T214842", ejecutado_en=AHORA, filas_origen=100,
                 filas_cargadas=90, filas_no_usadas=8, filas_cuarentena=2)


def _uso(carga_id: int, destino: str, **novedades) -> dict:
    return {"carga_id": carga_id, "destino": destino, "tabla_staging": "tabla_x", "leidas": 10, "cargadas": 10,
            "otra_toma": 0, "sin_valor": 0, "duplicado": 0, "cuarentena": 0, **novedades}


@pytest.fixture
def cumplen():
    """Resultados sintéticos de tres reglas de dimensiones distintas, todos sin incumplimientos."""
    return [Resultado("QR-INT-01", "fact_trauma.paciente_id -> dim_paciente", 50, 0),
            Resultado("QR-DUP-02", "dim_caida", 20, 0),
            Resultado("QR-EXA-03", "bridge_atencion_cie_10[diagnostico] (excel)", 40, 0)]


def _reporte(resultados, cargas=None, detalle=None) -> Reporte:
    return Reporte(modelo="completo", generado_en=AHORA, cargas=cargas if cargas is not None else [_carga(7, "redcap")],
                   detalle=detalle if detalle is not None else [], resultados=resultados)


class TestReporteVeredictoYResumen:
    def test_veredicto_segun_la_accion_de_cada_regla(self, cumplen):
        """
        Qué es: prueba unitaria del veredicto de la corrida.
        Qué hace: calcula el veredicto con todo cumplido, con una regla que advierte incumplida (QR-DOM-02) y con una
                  regla que bloquea incumplida (QR-INT-01).
        Esperado: Aprobada; Aprobada con advertencias; Rechazada. La que bloquea manda sobre la que advierte.
        """
        # Arrange: dos incumplimientos sintéticos
        advierte = Resultado("QR-DOM-02", "fact_trauma.peso entre 0.5 y 400", 50, 5)
        bloquea = Resultado("QR-INT-01", "fact_trauma.evento_id -> dim_evento_trauma", 50, 1)

        # Act
        veredictos = (_reporte(cumplen).veredicto(), _reporte([*cumplen, advierte]).veredicto(),
                      _reporte([*cumplen, advierte, bloquea]).veredicto())

        # Assert
        assert veredictos == ("Aprobada", "Aprobada con advertencias", "Rechazada")

    def test_resumen_cuenta_por_dimension_de_calidad(self, cumplen):
        """
        Qué es: prueba unitaria del resumen por dimensión (semáforo del reporte).
        Qué hace: resume tres reglas cumplidas, una que advierte incumplida y una que falla incumplida.
        Esperado: una fila por dimensión con sus cumplen, advierten y fallan; QR-INT-01 y QR-INT-02 comparten la
                  dimensión Integridad.
        """
        # Arrange
        extra = [Resultado("QR-DOM-02", "fact_trauma.peso entre 0.5 y 400", 50, 5),
                 Resultado("QR-INT-02", "fact_trauma.caida_id", 50, 2)]

        # Act
        resumen = {f["dimension"]: f for f in _reporte([*cumplen, *extra]).resumen()}

        # Assert
        assert resumen["Integridad"] == {"dimension": "Integridad", "cumplen": 1, "advierten": 0, "fallan": 1}
        assert resumen["Validez"]["advierten"] == 1
        assert resumen["Unicidad"]["cumplen"] == 1 and resumen["Exactitud"]["cumplen"] == 1

    def test_porcentaje_de_incumplimiento(self):
        """
        Qué es: prueba unitaria del porcentaje de incumplimiento de una regla.
        Qué hace: arma las filas de reglas para un incumplimiento de 1 sobre 8, una regla sin filas evaluadas y QR-EXA-03.
        Esperado: '12.50 %' para la primera; '—' para las otras dos (no hay denominador, o es una diferencia y no un
                  subconjunto).
        """
        # Arrange
        resultados = [Resultado("QR-DUP-02", "dim_a", 8, 1), Resultado("QR-DUP-02", "dim_b", 0, 0),
                      Resultado("QR-EXA-03", "bridge_x (excel)", 40, 3)]

        # Act
        porcentajes = [f["porcentaje"] for f in _reporte(resultados).reglas()]

        # Assert
        assert porcentajes == ["12.50 %", "—", "—"]


class TestReporteSalida:
    def test_markdown_tiene_las_secciones_y_solo_conteos(self, cumplen):
        """
        Qué es: prueba unitaria del Markdown del reporte.
        Qué hace: genera el texto con dos cargas, tres reglas y un uso con filas no usadas.
        Esperado: trae el veredicto y las seis secciones; el uso con novedad aparece en la reconciliación y los que no
                  tienen novedad, no; los nombres de fuente y de tabla están y no hay más que conteos.
        """
        # Arrange
        detalle = [_uso(7, "fact_trauma", otra_toma=3), _uso(7, "dim_caida")]
        reporte = _reporte(cumplen, cargas=[_carga(6, "excel"), _carga(7, "redcap")], detalle=detalle)

        # Act
        texto = reporte.a_markdown()

        # Assert
        assert "Veredicto: **Aprobada**" in texto
        for seccion in ("## 1. Cargas verificadas", "## 2. Resumen", "## 3. Reglas", "## 4. Reconciliación",
                        "## 5. Completitud", "## 6. Pendiente"):
            assert seccion in texto
        assert "| 7 | fact_trauma | tabla_x | 10 | 10 | 3 |" in texto
        assert "dim_caida | tabla_x" not in texto
        assert "excel" in texto and "redcap" in texto
        assert "| — | Total | — | — | 200 | 180 | 16 | 4 |" in texto

    def test_escribe_los_archivos_en_la_carpeta_de_la_ultima_carga(self, cumplen, tmp_path):
        """
        Qué es: prueba unitaria de la escritura del reporte en disco.
        Qué hace: escribe un reporte con las cargas 6 y 7 en una carpeta temporal y lee los CSV.
        Esperado: la carpeta es warehouse/completo/carga_id=7 con reporte.md y los cuatro CSV; reglas.csv tiene una
                  fila por regla con las columnas del diseño y reconciliacion.csv, una por uso.
        """
        # Arrange
        reporte = _reporte(cumplen, cargas=[_carga(6, "excel"), _carga(7, "redcap")], detalle=[_uso(7, "fact_trauma")])

        # Act
        carpeta = reporte.escribir(str(tmp_path))

        # Assert
        assert carpeta == tmp_path / "warehouse" / "completo" / "carga_id=7"
        assert sorted(p.name for p in carpeta.iterdir()) == ["completitud.csv", "reconciliacion.csv", "reglas.csv",
                                                             "reporte.md", "resumen.csv"]
        with open(carpeta / "reglas.csv", encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
        assert [f["regla"] for f in filas] == ["QR-INT-01", "QR-DUP-02", "QR-EXA-03"]
        assert set(filas[0]) == {"regla", "dimension", "verificacion", "evaluadas", "incumplen", "porcentaje", "estado"}
        with open(carpeta / "reconciliacion.csv", encoding="utf-8", newline="") as f:
            assert len(list(csv.DictReader(f))) == 1

    def test_sin_cargas_exitosas_usa_la_carpeta_sin_carga(self, tmp_path):
        """
        Qué es: prueba unitaria del reporte cuando la bitácora no tiene cargas exitosas.
        Qué hace: escribe un reporte sin cargas ni resultados.
        Esperado: la carpeta se llama carga_id=sin_carga y el Markdown avisa que no hay cargas, en vez de fallar.
        """
        # Arrange
        reporte = _reporte([], cargas=[])

        # Act
        carpeta = reporte.escribir(str(tmp_path))

        # Assert
        assert carpeta.name == "carga_id=sin_carga"
        assert "No hay cargas exitosas en la bitácora." in (carpeta / "reporte.md").read_text(encoding="utf-8")


class TestReporteCompletitud:
    def test_completitud_va_aparte_y_ordenada_por_porcentaje(self, cumplen):
        """
        Qué es: prueba unitaria del detalle de completitud (QR-NUL-02, informativa).
        Qué hace: arma un reporte con tres columnas de distinto porcentaje de vacíos y las reglas que ya cumplen.
        Esperado: la completitud lista las tres de mayor a menor porcentaje; no aparecen en la tabla de reglas ni en el
                  resumen por dimensión; y aunque tengan vacíos, el veredicto sigue siendo Aprobada.
        """
        # Arrange
        columnas = [Resultado("QR-NUL-02", "fact_trauma.peso", 100, 10), Resultado("QR-NUL-02", "fact_trauma.scq", 100, 90),
                    Resultado("QR-NUL-02", "fact_trauma.altura", 100, 40)]
        reporte = _reporte([*cumplen, *columnas])

        # Act
        completitud = reporte.completitud()

        # Assert
        assert [c["columna"] for c in completitud] == ["fact_trauma.scq", "fact_trauma.altura", "fact_trauma.peso"]
        assert completitud[0]["porcentaje"] == "90.00 %"
        assert all(r["regla"] != "QR-NUL-02" for r in reporte.reglas())
        assert "Completitud" not in {f["dimension"] for f in reporte.resumen()}
        assert reporte.veredicto() == "Aprobada"
