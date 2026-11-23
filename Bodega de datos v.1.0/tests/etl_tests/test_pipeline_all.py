"""
Pruebas del ETL completo (`pipeline.run_all` y `pipeline.candado_del_etl`).

Todo está simulado: no hay conexión a PostgreSQL, ni REDCap, ni Excel, ni lectura de datos. Las funciones de cada paso
son dobles que solo registran que se las llamó y con qué argumentos.
"""
import pytest

from etl import pipeline


@pytest.fixture
def etl_falso(monkeypatch):
    """
    Sustituye los cinco pasos de la corrida completa, el reporte de calidad, el candado y las dos consultas de estado
    por dobles que registran el orden de las llamadas. `excel_cargado` y `excel_extraido` fijan el estado del
    Excel; `veredicto` es lo que devuelve el reporte de calidad; `falla` nombra un paso que lanza error. Es un
    entorno aislado y sintético: ningún doble toca datos ni la base.
    """
    estado = {"llamadas": [], "excel_cargado": False, "excel_extraido": False, "falla": None,
              "veredicto": "Aprobada"}

    def paso(nombre):
        def doble(*args, **kwargs):
            estado["llamadas"].append((nombre, args, kwargs))
            if estado["falla"] == nombre:
                raise ValueError(f"fallo simulado en {nombre}")
        return doble

    class CandadoFalso:
        def __enter__(self):
            estado["llamadas"].append(("candado: tomado", (), {}))

        def __exit__(self, *excepcion):
            estado["llamadas"].append(("candado: liberado", (), {}))
            return False

    monkeypatch.setattr(pipeline, "candado_del_etl", CandadoFalso)
    monkeypatch.setattr(pipeline, "excel_cargado", lambda modelo: estado["excel_cargado"])
    monkeypatch.setattr(pipeline, "existe_corrida_exitosa", lambda fuente: estado["excel_extraido"])
    for nombre in ("run_historical_excel_load", "run_transform_excel", "run_load",
                   "run_incremental_redcap", "run_transform_redcap"):
        monkeypatch.setattr(pipeline, nombre, paso(nombre))

    def run_quality(modelo):
        estado["llamadas"].append(("run_quality", (modelo,), {}))
        return estado["veredicto"]

    monkeypatch.setattr(pipeline, "run_quality", run_quality)
    return estado


def _nombres(estado) -> list[str]:
    return [nombre for nombre, _, _ in estado["llamadas"]]


class TestRunAll:
    def test_con_el_excel_pendiente_corre_todos_los_pasos_en_orden(self, etl_falso):
        """
        Qué es: prueba unitaria de run_all con el Excel sin extraer ni cargar (primera corrida de una bodega vacía).
        Qué hace: ejecuta la corrida completa del modelo completo con los pasos simulados.
        Esperado: seis pasos en orden (extraer, transformar y cargar el Excel y luego REDCap) y al final el reporte de
                  calidad del modelo, todo dentro del candado; las dos cargas reciben modelo y fuente y ninguna
                  recibe force.
        """
        # Arrange: Excel pendiente (el fixture lo deja sin extraer ni cargar)

        # Act
        pasos = pipeline.run_all("completo")

        # Assert: orden, candado alrededor y cargas sin force
        assert _nombres(etl_falso) == [
            "candado: tomado", "run_historical_excel_load", "run_transform_excel", "run_load",
            "run_incremental_redcap", "run_transform_redcap", "run_load", "run_quality", "candado: liberado"]
        cargas = [(args, kwargs) for nombre, args, kwargs in etl_falso["llamadas"] if nombre == "run_load"]
        assert cargas == [(("completo", "excel"), {}), (("completo", "redcap"), {})]
        assert [estado for _, estado in pasos] == ["ok"] * 6 + ["veredicto: Aprobada"]
        assert ("run_quality", ("completo",), {}) in etl_falso["llamadas"]

    def test_con_el_excel_ya_cargado_solo_mueve_redcap(self, etl_falso):
        """
        Qué es: prueba unitaria de la regla del Excel histórico (se carga una sola vez).
        Qué hace: marca el Excel como ya cargado en el modelo y ejecuta la corrida completa.
        Esperado: ningún paso del Excel se ejecuta, los tres de REDCap y el reporte de calidad sí, y el resultado
                  deja constancia de que el Excel se omitió.
        """
        # Arrange
        etl_falso["excel_cargado"] = True

        # Act
        pasos = pipeline.run_all("completo")

        # Assert
        assert _nombres(etl_falso) == [
            "candado: tomado", "run_incremental_redcap", "run_transform_redcap", "run_load", "run_quality",
            "candado: liberado"]
        assert pasos[0] == ("excel", "omitido: ya cargado")

    def test_con_el_excel_extraido_pero_sin_cargar_no_lo_extrae_otra_vez(self, etl_falso):
        """
        Qué es: prueba unitaria de la reanudación del Excel (extracción hecha, carga pendiente).
        Qué hace: marca el Excel como extraído pero no cargado y ejecuta la corrida completa.
        Esperado: no se vuelve a extraer (su guardia lo rechazaría), pero sí se transforma y se carga.
        """
        # Arrange
        etl_falso["excel_extraido"] = True

        # Act
        pipeline.run_all("completo")

        # Assert
        nombres = _nombres(etl_falso)
        assert "run_historical_excel_load" not in nombres
        assert nombres.index("run_transform_excel") < nombres.index("run_load")

    def test_sin_excel_no_toca_el_excel_ni_consulta_su_estado(self, etl_falso, monkeypatch):
        """
        Qué es: prueba unitaria de la opción de dejar el Excel fuera.
        Qué hace: ejecuta la corrida con incluir_excel=False y hace que consultar el estado del Excel falle.
        Esperado: solo corren los tres pasos de REDCap y el reporte de calidad, y la consulta del estado del Excel
                  no se hace.
        """
        # Arrange: cualquier consulta del Excel sería un error
        def no_debe_llamarse(*_):
            raise AssertionError("no se debe consultar el Excel")
        monkeypatch.setattr(pipeline, "excel_cargado", no_debe_llamarse)

        # Act
        pasos = pipeline.run_all("completo", incluir_excel=False)

        # Assert
        assert [nombre for nombre in _nombres(etl_falso) if not nombre.startswith("candado")] == [
            "run_incremental_redcap", "run_transform_redcap", "run_load", "run_quality"]
        assert [estado for _, estado in pasos] == ["ok"] * 3 + ["veredicto: Aprobada"]

    def test_sin_extraccion_no_extrae_de_ninguna_fuente(self, etl_falso):
        """
        Qué es: prueba unitaria de la opción de trabajar sin red (extraer=False).
        Qué hace: ejecuta la corrida con el Excel pendiente y sin extraer, con extraer=False.
        Esperado: no se llama a ninguna extracción (ni del Excel ni de REDCap); sí se transforma, se carga y se
                  genera el reporte; el resultado deja constancia de la omisión.
        """
        # Arrange: Excel pendiente y sin extraer (el fixture lo deja así)

        # Act
        pasos = pipeline.run_all("completo", extraer=False)

        # Assert
        nombres = _nombres(etl_falso)
        assert "run_historical_excel_load" not in nombres and "run_incremental_redcap" not in nombres
        assert nombres.count("run_load") == 2 and "run_quality" in nombres
        assert ("extraer", "omitido: se usa la capa raw existente") in pasos

    def test_un_paso_que_falla_detiene_la_corrida_y_libera_el_candado(self, etl_falso):
        """
        Qué es: prueba unitaria del manejo de errores de run_all.
        Qué hace: hace fallar la transformación de REDCap, con el Excel ya cargado.
        Esperado: se propaga el error original, no se ejecutan la carga ni el reporte de calidad posteriores y el
                  candado se libera.
        """
        # Arrange
        etl_falso["excel_cargado"] = True
        etl_falso["falla"] = "run_transform_redcap"

        # Act + Assert: error propagado
        with pytest.raises(ValueError, match="fallo simulado en run_transform_redcap"):
            pipeline.run_all("completo")

        # Assert: ni la carga ni el reporte corrieron y el candado se liberó
        nombres = _nombres(etl_falso)
        assert "run_load" not in nombres and "run_quality" not in nombres
        assert nombres[-1] == "candado: liberado"

    def test_un_veredicto_rechazada_no_hace_fallar_la_corrida(self, etl_falso):
        """
        Qué es: prueba unitaria de la relación entre el reporte de calidad y la corrida completa.
        Qué hace: hace que el reporte de calidad devuelva "Rechazada" y ejecuta la corrida completa.
        Esperado: la corrida termina sin error y deja el veredicto en su último paso: los datos ya se cargaron y el
                  reporte es quien informa el problema.
        """
        # Arrange
        etl_falso["excel_cargado"] = True
        etl_falso["veredicto"] = "Rechazada"

        # Act
        pasos = pipeline.run_all("completo")

        # Assert
        assert pasos[-1] == ("calidad", "veredicto: Rechazada")


class TestCodigoDeSalida:
    @pytest.mark.parametrize("veredicto, codigo", [("Aprobada", 0), ("Aprobada con advertencias", 0), ("Rechazada", 2)])
    def test_el_codigo_depende_solo_del_veredicto(self, veredicto, codigo):
        """
        Qué es: prueba unitaria de `codigo_de_salida` (código de salida de --mode=all).
        Qué hace: le da los pasos de una corrida cuyo reporte de calidad dio cada uno de los tres veredictos.
        Esperado: 0 con "Aprobada" y con "Aprobada con advertencias"; 2 solo con "Rechazada".
        """
        # Arrange: pasos como los devuelve run_all (sintéticos)
        pasos = [("cargar redcap", "ok"), ("calidad", f"veredicto: {veredicto}")]

        # Act + Assert: el código sale solo del veredicto
        assert pipeline.codigo_de_salida(pasos) == codigo

    def test_main_termina_con_2_si_la_bodega_es_rechazada(self, etl_falso, monkeypatch):
        """
        Qué es: prueba unitaria de `main` con --mode=all y un reporte de calidad que rechaza la bodega.
        Qué hace: ejecuta main con los pasos simulados y el veredicto "Rechazada"; luego repite con "Aprobada".
        Esperado: con "Rechazada" el proceso termina con SystemExit(2) después de correr todos los pasos; con "Aprobada"
                  main vuelve sin salir con un código distinto de 0 (SystemExit(0)).
        """
        # Arrange: Excel ya cargado, sin red y argumentos de la línea de comandos simulados
        etl_falso["excel_cargado"] = True
        monkeypatch.setattr(pipeline.sys, "argv", ["etl.pipeline", "--mode=all", "--sin-extraccion"])

        # Act + Assert: rechazada
        etl_falso["veredicto"] = "Rechazada"
        with pytest.raises(SystemExit) as rechazada:
            pipeline.main()
        assert rechazada.value.code == 2 and "run_quality" in _nombres(etl_falso)

        # Act + Assert: aprobada
        etl_falso["veredicto"] = "Aprobada"
        with pytest.raises(SystemExit) as aprobada:
            pipeline.main()
        assert aprobada.value.code == 0


class TestCandadoDelEtl:
    @pytest.fixture
    def base_falsa(self, monkeypatch):
        """
        Engine y conexión simulados (sin PostgreSQL): registran las sentencias ejecutadas y si el engine se liberó.
        `ocupado` hace que el candado ya esté tomado por otra corrida. Sintético y aislado: no hay base real.
        """
        estado = {"sql": [], "dispose": 0, "ocupado": False}

        class Resultado:
            def __init__(self, valor):
                self.valor = valor

            def scalar(self):
                return self.valor

        class ConexionFalsa:
            def execution_options(self, **_):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sentencia, parametros=None):
                texto = str(sentencia)
                estado["sql"].append(texto)
                return Resultado(not estado["ocupado"] if "try_advisory" in texto else True)

        class EngineFalso:
            def connect(self):
                return ConexionFalsa()

            def dispose(self):
                estado["dispose"] += 1

        monkeypatch.setattr(pipeline, "_crear_engine", EngineFalso)
        return estado

    def test_toma_el_candado_y_lo_libera_al_terminar(self, base_falsa):
        """
        Qué es: prueba unitaria de candado_del_etl con el candado libre.
        Qué hace: entra y sale del contexto con un engine simulado.
        Esperado: pide el candado al entrar, lo libera al salir y libera el engine.
        """
        # Arrange: candado libre (el fixture lo deja así)

        # Act
        with pipeline.candado_del_etl():
            tomado = [s for s in base_falsa["sql"] if "pg_try_advisory_lock" in s]

        # Assert
        assert len(tomado) == 1
        assert any("pg_advisory_unlock" in s for s in base_falsa["sql"])
        assert base_falsa["dispose"] == 1

    def test_si_esta_ocupado_falla_sin_liberar_el_de_otro(self, base_falsa):
        """
        Qué es: prueba unitaria de candado_del_etl con otra corrida en curso.
        Qué hace: simula que el candado ya lo tiene otra conexión e intenta entrar.
        Esperado: RuntimeError y ninguna liberación (el candado ajeno no se toca); el engine se libera.
        """
        # Arrange: el candado está tomado
        base_falsa["ocupado"] = True

        # Act + Assert
        with pytest.raises(RuntimeError, match="en curso"):
            with pipeline.candado_del_etl():
                pytest.fail("no debería entrar al contexto")

        assert not any("pg_advisory_unlock" in s for s in base_falsa["sql"])
        assert base_falsa["dispose"] == 1
