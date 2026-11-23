import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from etl.load.warehouse.base import BaseLoader, reconciliar
from etl.load.warehouse.contrato import ContratoInvalido
from etl.load.warehouse.cuarentena import COLUMNA_REGLA, escribir_cuarentena
from etl.load.warehouse.factory import LoaderFactory

RUN_ID = "2026-10-24T120000"


# ---------------------------------------------------------------------------
# Dobles: Engine de SQLAlchemy y Loader de un modelo de prueba
# ---------------------------------------------------------------------------

class _Resultado:
    def __init__(self, valor):
        self._valor = valor

    def scalar(self):
        return self._valor


class _Conexion:
    def __init__(self, motor):
        self.motor = motor

    def execute(self, sentencia, parametros=None):
        self.motor.sentencias.append((str(sentencia), parametros))
        return _Resultado(self.motor.ya_cargado)


class _Contexto:
    def __init__(self, motor, tipo):
        self.motor, self.tipo = motor, tipo

    def __enter__(self):
        self.motor.aperturas.append(self.tipo)
        return _Conexion(self.motor)

    def __exit__(self, tipo_exc, exc, traza):
        if self.tipo == "begin":
            self.motor.cierres.append("rollback" if exc else "commit")
        return False


class MotorDoble:
    """
    Doble del Engine de SQLAlchemy: registra qué conexiones se abren, cómo termina cada transacción y qué
    sentencias se ejecutan, sin base de datos. `ya_cargado` es la respuesta de la guardia del Excel.
    """
    def __init__(self, ya_cargado: bool = False):
        self.ya_cargado = ya_cargado
        self.aperturas: list[str] = []
        self.cierres: list[str] = []
        self.sentencias: list[tuple[str, dict]] = []

    def begin(self):
        return _Contexto(self, "begin")

    def connect(self):
        return _Contexto(self, "connect")

    def registros_de_carga(self) -> list[dict]:
        return [parametros for sentencia, parametros in self.sentencias if "INSERT INTO etl_control.carga (" in sentencia]

    def registros_de_detalle(self) -> list[dict]:
        return [fila for sentencia, filas in self.sentencias if "INSERT INTO etl_control.carga_detalle" in sentencia
                for fila in filas]


USO = ("fact_doble", "informacion_demografica")


class LoaderDoble(BaseLoader):
    """Loader de un modelo de prueba: guarda lo que recibe y devuelve conteos por uso configurables."""
    modelo = "doble"

    def __init__(self, *args, edad_minima=None, usos=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.edad_minima, self.usos, self.recibidas = edad_minima, usos, None

    def separar_cuarentena(self, tablas, contrato):
        if self.edad_minima is None:
            return tablas, {}
        df = tablas["informacion_demografica"]
        rechazadas = df["edad"] < self.edad_minima
        return ({"informacion_demografica": df[~rechazadas]},
                {"informacion_demografica": df[rechazadas].assign(**{COLUMNA_REGLA: "QR-PRUEBA-01"})})

    def cargar(self, conexion, tablas, contrato):
        self.recibidas = tablas
        if self.usos is not None:
            return self.usos
        return {("fact_doble", tabla): {"cargadas": len(df)} for tabla, df in tablas.items()}


@pytest.fixture
def entorno(tmp_path):
    """
    Crea en una carpeta temporal un staging sintético por fuente (tres atenciones inventadas y una columna que el
    contrato no pide), el contrato del modelo de prueba y la raíz de la cuarentena. Sin datos clínicos reales.
    """
    for fuente, prefijo in (("redcap", "RC"), ("excel", "EX")):
        carpeta = tmp_path / "staging" / fuente
        carpeta.mkdir(parents=True)
        df = pd.DataFrame({"trauma_register_id": [f"{prefijo}-1", f"{prefijo}-2", f"{prefijo}-3"],
                           "edad": [30, 41, 25], "fuera_de_contrato": ["a", "b", "c"]})
        df.to_parquet(carpeta / "informacion_demografica.parquet", index=False)
        (carpeta / "manifiesto.json").write_text(json.dumps(
            {"run_id": RUN_ID, "source_type": fuente, "rows": {"informacion_demografica": 3}}), encoding="utf-8")

    columnas = {columna: {"origen": {"excel": f"informacion_demografica.{columna}",
                                     "redcap": f"informacion_demografica.{columna}"}}
                for columna in ("trauma_register_id", "edad")}
    filas = {"excel": "informacion_demografica", "redcap": "informacion_demografica"}
    staging = {fuente: {"informacion_demografica": {"grano": "atencion"}} for fuente in filas}
    contrato = tmp_path / "doble.yaml"
    contrato.write_text(yaml.safe_dump({"modelo": "doble", "version": 1, "staging": staging, "tablas": {
        "fact_doble": {"tipo": "hecho", "filas": filas, "columnas": columnas}}}), encoding="utf-8")
    return tmp_path


def _loader(entorno, motor, fuente="redcap", force=False, **kwargs) -> LoaderDoble:
    return LoaderDoble(fuente=fuente, engine=motor, staging_dir=str(entorno / "staging" / fuente),
                       ruta_contrato=str(entorno / "doble.yaml"), quarantine_dir=str(entorno / "cuarentena"),
                       force=force, **kwargs)


# ---------------------------------------------------------------------------
# Pruebas
# ---------------------------------------------------------------------------

class TestBaseLoaderValidacionesPrevias:
    @pytest.mark.parametrize("defecto", ["otro_modelo", "origen_inexistente"])
    def test_contrato_invalido_detiene_sin_abrir_conexion(self, entorno, defecto):
        """
        Qué es: prueba unitaria del Template Method de BaseLoader (pasos 1 y 3, previos a la base).
        Qué hace: ejecuta run() con un contrato de otro modelo y con uno que pide una columna que el staging no tiene.
        Esperado: ContratoInvalido y el motor sin ninguna conexión abierta (la bodega no se toca).
        """
        # Arrange: contrato con el defecto
        ruta = entorno / "doble.yaml"
        contrato = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        if defecto == "otro_modelo":
            contrato["modelo"] = "mini"
        else:
            contrato["tablas"]["fact_doble"]["columnas"]["edad"]["origen"]["redcap"] = "informacion_demografica.no_existe"
        ruta.write_text(yaml.safe_dump(contrato), encoding="utf-8")
        motor = MotorDoble()

        # Act + Assert: se detiene antes de conectarse
        with pytest.raises(ContratoInvalido):
            _loader(entorno, motor).run()
        assert motor.aperturas == []

    def test_staging_de_otra_fuente_se_rechaza_sin_abrir_conexion(self, entorno):
        """
        Qué es: prueba unitaria de la comprobación de la fuente del manifiesto.
        Qué hace: apunta el Loader de REDCap a una carpeta cuyo manifiesto es del Excel.
        Esperado: ValueError que nombra las dos fuentes y ninguna conexión abierta.
        """
        # Arrange: Loader de REDCap sobre el staging del Excel
        motor = MotorDoble()
        loader = _loader(entorno, motor)
        loader.staging_dir = str(entorno / "staging" / "excel")

        # Act + Assert: rechazo sin conexión
        with pytest.raises(ValueError, match="excel"):
            loader.run()
        assert motor.aperturas == []


class TestBaseLoaderGuardiaExcel:
    def test_excel_ya_cargado_sin_force_se_rechaza_sin_transaccion(self, entorno):
        """
        Qué es: prueba unitaria de la guardia del Excel (se carga una sola vez).
        Qué hace: ejecuta la carga del Excel cuando etl_control.carga ya tiene una exitosa para el modelo.
        Esperado: RuntimeError que sugiere --force; solo se abrió la conexión de lectura de la guardia, sin
                  transacción ni registro, y la consulta filtra por modelo y fuente.
        """
        # Arrange: la guardia responde que ya hubo una carga exitosa
        motor = MotorDoble(ya_cargado=True)

        # Act + Assert: rechazo
        with pytest.raises(RuntimeError, match="--force"):
            _loader(entorno, motor, fuente="excel").run()

        # Assert: solo la consulta de la guardia
        assert motor.aperturas == ["connect"]
        assert motor.sentencias[0][1] == {"modelo": "doble", "fuente": "excel"}
        assert motor.registros_de_carga() == []

    def test_excel_con_force_carga_sin_consultar_la_guardia(self, entorno):
        """
        Qué es: prueba unitaria de --force en la carga del Excel.
        Qué hace: ejecuta la carga del Excel con force aunque ya haya una exitosa.
        Esperado: no se consulta la guardia; se abre una transacción, se confirma y queda registrada como exitosa.
        """
        # Arrange: ya cargado, pero con force
        motor = MotorDoble(ya_cargado=True)

        # Act: cargar
        resultado = _loader(entorno, motor, fuente="excel", force=True).run()

        # Assert: una transacción confirmada y su registro
        assert motor.aperturas == ["begin"]
        assert motor.cierres == ["commit"]
        assert [r["exitosa"] for r in motor.registros_de_carga()] == [True]
        assert resultado.fuente == "excel"


class TestBaseLoaderCorrida:
    def test_carga_normal_lee_solo_el_contrato_y_registra_la_corrida(self, entorno):
        """
        Qué es: prueba unitaria de run() de extremo a extremo con dobles (caso normal de REDCap).
        Qué hace: carga el staging sintético de REDCap en el modelo de prueba.
        Esperado: REDCap no consulta la guardia; cargar() recibe solo las columnas del contrato (no
                  fuera_de_contrato); una transacción confirmada con un registro exitoso de 3 = 3 + 0 + 0, su
                  balance por uso en carga_detalle, y el resultado lleva el run_id del staging.
        """
        # Arrange: motor limpio
        motor = MotorDoble()
        loader = _loader(entorno, motor)

        # Act: cargar
        resultado = loader.run()

        # Assert: lectura mínima
        assert list(loader.recibidas["informacion_demografica"].columns) == ["edad", "trauma_register_id"]

        # Assert: transacción y registro
        assert motor.aperturas == ["begin"]
        assert motor.cierres == ["commit"]
        assert motor.registros_de_carga() == [{
            "modelo": "doble", "fuente": "redcap", "run_id_staging": RUN_ID,
            "filas_origen": 3, "filas_cargadas": 3, "filas_no_usadas": 0, "filas_cuarentena": 0,
            "atenciones_nuevas": 0, "atenciones_modificadas": 0, "atenciones_sin_cambio": 0,
            "atenciones_eliminadas": 0, "ruta_cuarentena": None, "exitosa": True,
        }]
        assert [(d["destino"], d["tabla_staging"], d["leidas"], d["cargadas"]) for d in motor.registros_de_detalle()
                ] == [(*USO, 3, 3)]
        assert resultado.run_id_staging == RUN_ID
        assert resultado.ruta_cuarentena is None

    def test_cuarentena_se_escribe_y_reconcilia(self, entorno):
        """
        Qué es: prueba unitaria de la cuarentena dentro de run().
        Qué hace: el Loader aparta la atención con edad menor que 28 (regla sintética QR-PRUEBA-01).
        Esperado: se cargan 2, queda 1 en cuarentena con su regla en Parquet bajo <modelo>/<fuente>/run_id=...,
                  y el balance del uso y el registro de la corrida reconcilian 3 = 2 + 0 + 1.
        """
        # Arrange: Loader con regla de cuarentena
        motor = MotorDoble()

        # Act: cargar
        resultado = _loader(entorno, motor, edad_minima=28).run()

        # Assert: balance del uso y fila apartada en disco con su regla
        assert resultado.detalle == {USO: {"leidas": 3, "cargadas": 2, "otra_toma": 0, "sin_valor": 0,
                                           "duplicado": 0, "cuarentena": 1}}
        assert resultado.filas_cuarentena == {"informacion_demografica": 1}
        apartada = pd.read_parquet(f"{resultado.ruta_cuarentena}/informacion_demografica.parquet")
        assert apartada["trauma_register_id"].tolist() == ["RC-3"]
        assert apartada[COLUMNA_REGLA].tolist() == ["QR-PRUEBA-01"]
        assert "doble" in resultado.ruta_cuarentena and "redcap" in resultado.ruta_cuarentena

        # Assert: el registro guarda las sumas
        registro = motor.registros_de_carga()[0]
        assert (registro["filas_origen"], registro["filas_cargadas"], registro["filas_no_usadas"],
                registro["filas_cuarentena"]) == (3, 2, 0, 1)
        assert registro["ruta_cuarentena"] == resultado.ruta_cuarentena

    def test_carga_que_no_reconcilia_se_revierte_y_registra_la_falla(self, entorno):
        """
        Qué es: prueba unitaria de la reconciliación obligatoria (QR-EXA-01) y del registro de la falla.
        Qué hace: el Loader informa 2 filas cargadas de 3 leídas, sin motivo ni cuarentena para la tercera.
        Esperado: ValueError de reconciliación; la transacción de la carga se revierte y, en otra transacción
                  confirmada, queda un único registro con exitosa = False, 0 filas cargadas y sin detalle por uso.
        """
        # Arrange: Loader que "pierde" una fila
        motor = MotorDoble()

        # Act + Assert: la carga no reconcilia
        with pytest.raises(ValueError, match="no reconcilia"):
            _loader(entorno, motor, usos={USO: {"cargadas": 2}}).run()

        # Assert: carga revertida y falla registrada aparte
        assert motor.cierres == ["rollback", "commit"]
        registros = motor.registros_de_carga()
        assert len(registros) == 1
        assert registros[0]["exitosa"] is False
        assert registros[0]["filas_cargadas"] == 0
        assert registros[0]["ruta_cuarentena"] is None
        assert motor.registros_de_detalle() == []

    def test_carga_fallida_con_cuarentena_registra_su_ruta(self, entorno):
        """
        Qué es: prueba unitaria del registro de la ruta de la cuarentena en una carga fallida (QR-TRZ-03).
        Qué hace: el Loader aparta 1 fila de 3 (regla sintética) y luego informa solo 1 cargada, así que no reconcilia.
        Esperado: ValueError; el registro de la falla guarda las 3 filas leídas, 1 en cuarentena y la carpeta donde se
                  escribió el Parquet (la cuarentena se escribe antes de la transacción), que existe en disco.
        """
        # Arrange: Loader con cuarentena que además "pierde" una fila
        motor = MotorDoble()

        # Act + Assert: la carga no reconcilia
        with pytest.raises(ValueError, match="no reconcilia"):
            _loader(entorno, motor, edad_minima=28, usos={USO: {"cargadas": 1}}).run()

        # Assert: la falla conserva la ruta de lo que sí quedó en disco
        (registro,) = motor.registros_de_carga()
        assert registro["exitosa"] is False and registro["filas_cuarentena"] == 1
        assert registro["ruta_cuarentena"] is not None and Path(registro["ruta_cuarentena"]).is_dir()


class TestReconciliacionYCuarentena:
    def test_reconciliar_por_uso_con_motivos_y_tabla_compartida(self):
        """
        Qué es: prueba unitaria de reconciliar por uso (QR-EXA-01).
        Qué hace: reconcilia una tabla de tomas (4 filas: 1 cargada, 2 de otra toma, 1 sin valor) y una tabla
                  compartida por el hecho y un puente (3 filas, una en cuarentena), cada uso con su propio balance.
        Esperado: no lanza; devuelve el balance de cada uso con los seis conteos (los motivos ausentes en 0) y la
                  cuarentena de la tabla repetida en los dos usos.
        """
        # Arrange: conteos sintéticos por tabla y por uso
        origen = {"signos": 4, "mecanismo": 3}
        usos = {
            ("fact", "signos"): {"cargadas": 1, "otra_toma": 2, "sin_valor": 1},
            ("fact", "mecanismo"): {"cargadas": 2},
            ("bridge[rol]", "mecanismo"): {"cargadas": 1, "sin_valor": 1},
        }

        # Act
        detalle = reconciliar(origen, usos, {"mecanismo": 1})

        # Assert
        assert detalle[("fact", "signos")] == {"leidas": 4, "cargadas": 1, "otra_toma": 2, "sin_valor": 1,
                                               "duplicado": 0, "cuarentena": 0}
        assert detalle[("bridge[rol]", "mecanismo")]["cuarentena"] == 1
        assert detalle[("fact", "mecanismo")]["cuarentena"] == 1

    def test_reconciliar_nombra_solo_los_usos_descuadrados(self):
        """
        Qué es: prueba unitaria de los mensajes de reconciliar.
        Qué hace: reconcilia dos usos, uno que cuadra con cuarentena y otro al que le falta una fila sin motivo.
        Esperado: ValueError que nombra el uso descuadrado y no el que cuadra; con la fila contada como duplicado
                  cuadra.
        """
        # Arrange: conteos sintéticos
        origen = {"a": 3, "b": 2}

        # Act + Assert: b no cuadra
        with pytest.raises(ValueError) as error:
            reconciliar(origen, {("fact", "a"): {"cargadas": 2}, ("puente", "b"): {"cargadas": 1}}, {"a": 1})
        assert "puente <- b" in str(error.value) and "fact <- a" not in str(error.value)

        # Act + Assert: con la fila de b como duplicado, cuadra
        reconciliar(origen, {("fact", "a"): {"cargadas": 2}, ("puente", "b"): {"cargadas": 1, "duplicado": 1}},
                    {"a": 1})

    def test_reconciliar_rechaza_tabla_sin_uso_uso_sin_tabla_y_motivo_desconocido(self):
        """
        Qué es: prueba unitaria de la cobertura que exige reconciliar.
        Qué hace: reconcilia con una tabla leída que ningún uso explica, con un uso de una tabla no leída y con un
                  motivo que no está en MOTIVOS_NO_USADAS.
        Esperado: ValueError en los tres casos, con la tabla sin uso, el uso sobrante o el motivo desconocido en el
                  mensaje (el Loader no puede dejar filas sin explicar ni inventar motivos).
        """
        # Arrange: el uso correcto de "a"
        bien = {("fact", "a"): {"cargadas": 1}}

        # Act + Assert: tabla "b" leída sin uso
        with pytest.raises(ValueError, match=r"sin uso: \['b'\]"):
            reconciliar({"a": 1, "b": 1}, bien, {})

        # Act + Assert: uso de una tabla que no se leyó
        with pytest.raises(ValueError, match="fact <- c"):
            reconciliar({"a": 1}, {**bien, ("fact", "c"): {"cargadas": 0}}, {})

        # Act + Assert: motivo desconocido
        with pytest.raises(ValueError, match="descartada"):
            reconciliar({"a": 2}, {("fact", "a"): {"cargadas": 1, "descartada": 1}}, {})

    def test_cuarentena_exige_regla_y_no_crea_carpetas_vacias(self, tmp_path):
        """
        Qué es: prueba unitaria de escribir_cuarentena.
        Qué hace: escribe una cuarentena vacía y otra con una fila sin regla.
        Esperado: la vacía devuelve None y no crea carpeta; la que no tiene regla falla con ValueError.
        """
        # Arrange: una tabla vacía y una fila sin regla
        vacia = {"t": pd.DataFrame({"trauma_register_id": []})}
        sin_regla = {"t": pd.DataFrame({"trauma_register_id": ["RC-1"]})}

        # Act + Assert: vacía, sin carpeta
        assert escribir_cuarentena(vacia, str(tmp_path / "q"), "doble", "redcap", RUN_ID) is None
        assert not (tmp_path / "q").exists()

        # Act + Assert: sin regla, rechazo
        with pytest.raises(ValueError, match=COLUMNA_REGLA):
            escribir_cuarentena(sin_regla, str(tmp_path / "q"), "doble", "redcap", RUN_ID)


class TestLoaderFactory:
    def test_registra_y_crea_el_loader_del_modelo(self, monkeypatch, entorno):
        """
        Qué es: prueba unitaria del registro de LoaderFactory.
        Qué hace: registra LoaderDoble como modelo "doble" y lo pide con su configuración.
        Esperado: devuelve una instancia de LoaderDoble configurada con la fuente; el nombre no distingue mayúsculas.
        """
        # Arrange: registro aislado de la prueba
        monkeypatch.setattr(LoaderFactory, "_registry", {})
        LoaderFactory.register("doble", LoaderDoble)

        # Act: pedir el Loader
        loader = LoaderFactory.get_loader("DOBLE", {
            "fuente": "redcap", "engine": MotorDoble(), "staging_dir": str(entorno / "staging" / "redcap"),
            "ruta_contrato": str(entorno / "doble.yaml"), "quarantine_dir": str(entorno / "cuarentena"),
        })

        # Assert: instancia correcta
        assert isinstance(loader, LoaderDoble)
        assert loader.fuente == "redcap"

    def test_rechaza_un_modelo_sin_loader(self, monkeypatch):
        """
        Qué es: prueba unitaria del rechazo de LoaderFactory.
        Qué hace: pide el Loader de un modelo no registrado.
        Esperado: ValueError que lista los modelos disponibles.
        """
        # Arrange: registro con un solo modelo
        monkeypatch.setattr(LoaderFactory, "_registry", {"doble": LoaderDoble})

        # Act + Assert: rechazo con los disponibles
        with pytest.raises(ValueError, match="doble"):
            LoaderFactory.get_loader("completo", {})

    def test_configuracion_invalida_da_type_error(self, monkeypatch):
        """
        Qué es: prueba unitaria de la configuración que recibe la fábrica.
        Qué hace: pide el Loader con un parámetro que no existe.
        Esperado: TypeError que nombra el modelo.
        """
        # Arrange: registro con el doble
        monkeypatch.setattr(LoaderFactory, "_registry", {"doble": LoaderDoble})

        # Act + Assert: parámetro desconocido
        with pytest.raises(TypeError, match="doble"):
            LoaderFactory.get_loader("doble", {"parametro_inexistente": 1})

    def test_fuente_desconocida_se_rechaza_al_construir(self, entorno):
        """
        Qué es: prueba unitaria de la validación de la fuente en BaseLoader.
        Qué hace: construye un Loader con una fuente que no es excel ni redcap.
        Esperado: ValueError al construir, antes de cualquier lectura.
        """
        # Arrange + Act + Assert: rechazo inmediato
        with pytest.raises(ValueError, match="Fuente desconocida"):
            _loader(entorno, MotorDoble(), fuente="sql")
