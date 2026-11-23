"""
Pruebas de `pipeline.run_quality`: el reporte de calidad de la bodega y el registro de su veredicto en
etl_control.calidad.

Todo está simulado: no hay conexión a PostgreSQL ni lectura de la bodega. El reporte, el engine y el contrato son dobles
sintéticos que solo registran qué se les pidió.
"""
import pytest

from etl import pipeline


@pytest.fixture
def calidad_falsa(monkeypatch):
    """
    Sustituye el contrato, el engine y la construcción del reporte por dobles. `insertados` guarda lo que se escribió en
    la base, `dispose` cuenta cuántas veces se liberó el engine, `error` hace fallar la construcción del reporte y
    `reglas` son las cuatro reglas inventadas que devuelve (una que falla, una que advierte, una que cumple y una que
    solo informa) y `kwargs` guarda los argumentos con que se pidió el reporte.
    Sintético y aislado: ningún doble toca datos, la base ni el disco.
    """
    estado = {"insertados": [], "dispose": 0, "error": None, "reglas": [
        {"regla": "QR-DOM-02", "verificacion": "fact_trauma.iss", "evaluadas": 90, "incumplen": 4, "estado": "Advierte"},
        {"regla": "QR-INT-04", "verificacion": "fact_trauma: atenciones con huella", "evaluadas": 100, "incumplen": 2,
         "estado": "Falla"},
        {"regla": "QR-INT-01", "verificacion": "fact_trauma.paciente_id -> dim_paciente", "evaluadas": 100,
         "incumplen": 0, "estado": "Cumple"},
        {"regla": "QR-NUL-02", "verificacion": "fact_trauma.peso", "evaluadas": 100, "incumplen": 30,
         "estado": "Informa"}]}

    class ReporteFalso:
        def escribir(self):
            return "reportes/sintetico/carga_id=7"

        def veredicto(self):
            return "Aprobada con advertencias"

        def resumen(self):
            return [{"dimension": "Integridad", "cumplen": 5, "advierten": 0, "fallan": 0},
                    {"dimension": "Validez", "cumplen": 3, "advierten": 2, "fallan": 1}]

        def reglas(self):
            return estado["reglas"]

    class ConexionFalsa:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sentencia, parametros=None):
            estado["insertados"].append((str(sentencia), parametros))

    class EngineFalso:
        def connect(self):
            return ConexionFalsa()

        def begin(self):
            return ConexionFalsa()

        def dispose(self):
            estado["dispose"] += 1

    def construir_reporte(*_, **kwargs):
        estado["kwargs"] = kwargs
        if estado["error"]:
            raise estado["error"]
        return ReporteFalso()

    monkeypatch.setattr(pipeline, "_crear_engine", EngineFalso)
    monkeypatch.setattr(pipeline, "leer_contrato", lambda *_: object())
    # Las listas sintéticas que "lee" el doble: así la prueba no depende de que exista config/valores_permitidos.yaml
    monkeypatch.setattr(pipeline, "leer_permitidos", lambda *_: {"dim_sintetica": {"atributo": ["a", "b"]}})
    monkeypatch.setattr(pipeline, "_rol_lector", lambda: "lector_sintetico")
    monkeypatch.setattr(pipeline, "construir_reporte", construir_reporte)
    return estado


class TestRunQuality:
    def test_registra_el_veredicto_y_los_conteos_en_etl_control(self, calidad_falsa):
        """
        Qué es: prueba unitaria de run_quality con reporte, engine y contrato simulados.
        Qué hace: ejecuta el reporte de calidad del modelo completo.
        Esperado: devuelve el veredicto del reporte y escribe una fila en etl_control.calidad con el modelo, el
                  veredicto, la suma de los conteos de todas las dimensiones (8 cumplen, 2 advierten, 1 fallan) y la
                  carpeta del reporte; el engine se libera.
        """
        # Arrange: el doble del reporte trae dos dimensiones con sus conteos

        # Act
        veredicto = pipeline.run_quality("completo")

        # Assert
        assert veredicto == "Aprobada con advertencias"
        ((sentencia, parametros),) = calidad_falsa["insertados"]
        assert "INSERT INTO etl_control.calidad" in sentencia
        assert parametros == {"modelo": "completo", "veredicto": "Aprobada con advertencias",
                              "ruta": "reportes/sintetico/carga_id=7", "cumplen": 8, "advierten": 2, "fallan": 1}
        assert calidad_falsa["dispose"] == 1

    def test_si_el_reporte_falla_no_registra_nada_y_libera_el_engine(self, calidad_falsa):
        """
        Qué es: prueba unitaria del manejo de errores de run_quality.
        Qué hace: hace fallar la construcción del reporte.
        Esperado: se propaga el error original, no se escribe ninguna fila (no hay veredicto que guardar) y el engine
                  igual se libera.
        """
        # Arrange: la construcción del reporte falla
        calidad_falsa["error"] = RuntimeError("fallo simulado del reporte")

        # Act + Assert: error propagado
        with pytest.raises(RuntimeError, match="fallo simulado del reporte"):
            pipeline.run_quality("completo")

        # Assert: nada escrito y engine liberado
        assert calidad_falsa["insertados"] == []
        assert calidad_falsa["dispose"] == 1

    def test_el_log_lista_las_reglas_que_fallan_y_advierten_con_sus_conteos(self, calidad_falsa, caplog):
        """
        Qué es: prueba unitaria de los motivos del veredicto en el log de run_quality.
        Qué hace: ejecuta el reporte con cuatro reglas inventadas (Falla, Advierte, Cumple e Informa) y lee el log.
        Esperado: el log nombra la regla que falla y la que advierte con su verificación y su conteo, la que falla antes
                  que la que advierte, y no nombra la que cumple ni la que solo informa.
        """
        # Arrange: las reglas del doble vienen del fixture

        # Act
        with caplog.at_level("INFO", logger="etl.pipeline"):
            pipeline.run_quality("completo")

        # Assert
        mensajes = [r.getMessage() for r in caplog.records]
        falla = "  Falla QR-INT-04: fact_trauma: atenciones con huella (2 de 100)"
        advierte = "  Advierte QR-DOM-02: fact_trauma.iss (4 de 90)"
        assert falla in mensajes and advierte in mensajes
        assert mensajes.index(falla) < mensajes.index(advierte)
        assert not any("QR-INT-01" in m or "QR-NUL-02" in m for m in mensajes)


class TestRunQualityValoresPermitidos:
    def test_con_el_archivo_pasa_las_listas_al_reporte(self, calidad_falsa, tmp_path):
        """
        Qué es: prueba unitaria de la conexión de QR-DOM-04 en run_quality, con el archivo de listas presente.
        Qué hace: ejecuta run_quality con un archivo de valores permitidos vacío (el doble de `leer_permitidos` lo
                  sustituye por listas sintéticas).
        Esperado: el reporte se construye con esas listas en `permitidos`.
        """
        # Arrange: un archivo que existe; su contenido no importa porque la lectura está simulada
        archivo = tmp_path / "valores_permitidos.yaml"
        archivo.write_text("", encoding="utf-8")

        # Act
        pipeline.run_quality("completo", valores_permitidos_path=str(archivo))

        # Assert
        assert calidad_falsa["kwargs"]["permitidos"] == {"dim_sintetica": {"atributo": ["a", "b"]}}

    def test_sin_el_archivo_no_evalua_la_regla_y_lo_registra_en_el_log(self, calidad_falsa, tmp_path, caplog):
        """
        Qué es: prueba unitaria de la conexión de QR-DOM-04 en run_quality, sin el archivo de listas.
        Qué hace: ejecuta run_quality apuntando a un archivo que no existe.
        Esperado: el reporte se construye con `permitidos=None` (la regla no se evalúa) y el log dice por qué.
        """
        # Arrange: ruta inexistente
        inexistente = str(tmp_path / "no_existe.yaml")

        # Act
        with caplog.at_level("INFO", logger="etl.pipeline"):
            pipeline.run_quality("completo", valores_permitidos_path=inexistente)

        # Assert
        assert calidad_falsa["kwargs"]["permitidos"] is None
        assert f"Sin {inexistente}: no se evalúa QR-DOM-04" in [r.getMessage() for r in caplog.records]
