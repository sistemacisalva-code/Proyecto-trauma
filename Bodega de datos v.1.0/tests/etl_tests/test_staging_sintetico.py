import csv
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from etl.load.warehouse.contrato import CLAVE_ATENCION, leer_contrato
from etl.load.warehouse.staging import esquema_staging, leer_manifiesto, leer_tablas
from tests.fixtures.staging_sintetico import (
    COLUMNA_FUERA_DEL_CONTRATO, FECHA_FUERA_DE_CALENDARIO, PERFIL_COMUN, RANGOS_VALIDOS, generar_staging,
)

RAIZ = Path(__file__).resolve().parents[2]
CONTRATO_COMPLETO = RAIZ / "config" / "contratos" / "completo.yaml"
# Salida local de scripts/esquema_staging.py (solo nombres y tipos); sin ella, la prueba de tipos se omite
ESQUEMA_STAGING = RAIZ / "scripts" / "esquema_staging.csv"
FUENTES = ("excel", "redcap")


@pytest.fixture(scope="module")
def contrato():
    """
    Contrato real del modelo completo. Solo se lee el YAML versionado: no toca el staging real ni datos de
    pacientes. Es el mismo contrato que usará el CompletoLoader, para que el staging sintético tenga su forma.
    """
    return leer_contrato(str(CONTRATO_COMPLETO), "completo")


@pytest.fixture(params=FUENTES)
def staging(request, tmp_path, contrato):
    """
    Staging sintético de una fuente en una carpeta temporal propia de la prueba (aislada: se borra al terminar).
    Valores inventados con semilla fija, sin ningún dato real.
    """
    return generar_staging(tmp_path / request.param, request.param, contrato)


def _tabla(staging, nombre: str) -> list[dict]:
    return pq.read_table(staging.carpeta / f"{nombre}.parquet").to_pylist()


def _de(filas: list[dict], clave: str) -> list[dict]:
    return [f for f in filas if f[CLAVE_ATENCION] == clave]


class TestStagingSinteticoForma:
    def test_pasa_el_manifiesto_y_el_contrato_real(self, staging, contrato):
        """
        Qué es: prueba unitaria del generador de staging sintético frente al contrato del completo.
        Qué hace: genera el staging de la fuente y lo valida con leer_manifiesto y Contrato.validar_contra, los mismos
                  pasos 2 y 3 de BaseLoader.run().
        Esperado: el manifiesto describe exactamente los Parquet escritos (fuente correcta) y el contrato no reporta
                  columnas ausentes ni tipos incompatibles de fechas, horas y banderas.
        """
        # Arrange: staging generado por el fixture
        columnas = contrato.columnas_por_tabla(staging.fuente)

        # Act
        manifiesto = leer_manifiesto(str(staging.carpeta))
        contrato.validar_contra(esquema_staging(str(staging.carpeta), list(columnas)), staging.fuente)

        # Assert: misma fuente y mismas tablas que el contrato pide (validar_contra no lanzó)
        assert manifiesto["source_type"] == staging.fuente
        assert set(manifiesto["rows"]) == set(columnas)
        assert manifiesto["rows"] == staging.filas

    def test_es_determinista(self, tmp_path, contrato):
        """
        Qué es: prueba unitaria de reproducibilidad del generador (semilla fija).
        Qué hace: genera dos veces el staging del Excel con la misma semilla en carpetas distintas.
        Esperado: cada Parquet es idéntico en esquema y contenido; los resultados de la tesis se pueden repetir.
        """
        # Arrange: dos carpetas aisladas
        primera, segunda = tmp_path / "a", tmp_path / "b"

        # Act
        a = generar_staging(primera, "excel", contrato)
        generar_staging(segunda, "excel", contrato)

        # Assert: tabla por tabla
        for tabla in a.filas:
            assert pq.read_table(primera / f"{tabla}.parquet").equals(pq.read_table(segunda / f"{tabla}.parquet"))

    def test_tipos_coinciden_con_el_staging_real(self, staging, contrato):
        """
        Qué es: prueba unitaria de fidelidad del generador al esquema real (solo metadatos).
        Qué hace: compara el tipo de Arrow de cada columna sintética con scripts/esquema_staging.csv (nombres y tipos
                  del staging real, sin filas); si el archivo local no está, la prueba se omite.
        Esperado: cada columna que pide el contrato tiene en el staging sintético el mismo tipo que en el real.
        """
        # Arrange: esquema real (metadatos) y sintético
        if not ESQUEMA_STAGING.is_file():
            pytest.skip("Falta scripts/esquema_staging.csv (local, sin versionar)")
        with open(ESQUEMA_STAGING, encoding="utf-8") as f:
            real = {(r["tabla"], r["columna"]): r["tipo_arrow"] for r in csv.DictReader(f)
                    if r["fuente"] == staging.fuente}
        columnas = contrato.columnas_por_tabla(staging.fuente)

        # Act
        sintetico = esquema_staging(str(staging.carpeta), list(columnas))

        # Assert: todas las diferencias juntas, para corregir el generador de una vez
        distintos = [f"{t}.{c}: real {real.get((t, c))}, sintético {sintetico[t][c]}"
                     for t, cols in columnas.items() for c in cols if real.get((t, c)) != sintetico[t][c]]
        assert distintos == []

    def test_la_lectura_del_contrato_no_trae_columnas_fuera_de_el(self, staging, contrato):
        """
        Qué es: prueba unitaria de minimización (TC-CAR-08) con el staging sintético.
        Qué hace: lee el staging con leer_tablas y las columnas que pide el contrato.
        Esperado: la columna fuera del contrato existe en el Parquet pero no en lo leído.
        """
        # Arrange: la columna está en el archivo
        assert COLUMNA_FUERA_DEL_CONTRATO in pq.read_schema(staging.carpeta / "informacion_demografica.parquet").names

        # Act
        tablas = leer_tablas(str(staging.carpeta), contrato.columnas_por_tabla(staging.fuente))

        # Assert: no llega a lo que carga el Loader
        assert COLUMNA_FUERA_DEL_CONTRATO not in tablas["informacion_demografica"].columns


class TestStagingSinteticoCasos:
    def test_casos_comunes_a_las_dos_fuentes(self, staging):
        """
        Qué es: prueba unitaria de los casos inyectados que las pruebas de integración de la carga usan como resultado esperado.
        Qué hace: busca cada caso común por su atención en las tablas del staging sintético.
        Esperado: perfil igual en las atenciones 1 y 2; la vacía sin filas en tablas de varias filas; cuatro tomas de
                  signos vitales (una sin fecha) y dos de laboratorio en la atención de tomas; llegada antes de 2011;
                  alta con segundos; dos procedimientos en orden inverso a su fecha; y una fila de procedimientos de
                  una atención que no está en las filas del hecho.
        """
        # Arrange: tablas sintéticas de la fuente
        demografia = _tabla(staging, "informacion_demografica")
        signos = _tabla(staging, "signos_vitales")
        procedimientos = _tabla(staging, "procedimientos")

        # Act: no aplica, se inspeccionan los casos escritos

        # Assert: un bloque por caso
        perfiles = [{k: f[k] for k in PERFIL_COMUN} for c in staging.ids["perfil_compartido"] for f in _de(demografia, c)]
        assert perfiles == [PERFIL_COMUN, PERFIL_COMUN]

        assert _de(signos, staging.id("vacia")) == [] and _de(procedimientos, staging.id("vacia")) == []

        tomas = _de(signos, staging.id("tomas"))
        assert len(tomas) == 4 and sum(f["fecha_y_hora_de_signos_vitales"] is None for f in tomas) == 1
        assert len(_de(_tabla(staging, "laboratorio"), staging.id("tomas"))) == 2

        (llegada,) = _de(demografia, staging.id("fuera_de_calendario"))
        assert llegada["fecha_y_hora_de_llegada_del_paciente"] == FECHA_FUERA_DE_CALENDARIO

        (alta,) = _de(_tabla(staging, "hospitalizacion"), staging.id("hora_con_segundos"))
        assert alta["fecha_y_hora_de_alta"].second == 45

        orden = [f["fecha_y_hora_de_procedimiento"] for f in _de(procedimientos, staging.id("orden_procedimientos"))]
        assert len(orden) == 2 and orden[0] > orden[1]

        huerfana = staging.id("huerfana")
        assert huerfana not in staging.atenciones and len(_de(procedimientos, huerfana)) == 1

    def test_casos_propios_del_excel(self, tmp_path, contrato):
        """
        Qué es: prueba unitaria de los casos que solo existen en el Excel (hojas hijas y banderas de mapeo CIE-10).
        Qué hace: genera el staging del Excel y revisa las atenciones de cie_sin_mapeo, sustancia_repetida, lesiones,
                  complicacion_sin_mapeo y la hoja hija de quemaduras en la atención de tomas.
        Esperado: un diagnóstico mapeado y dos textos sin mapear, uno de ellos repetido (texto_origen y
                  duplicado); la misma sustancia dos veces; dos lesiones y un mecanismo primario de la atención; la
                  misma forma en las complicaciones, todas en el mismo lugar; dos quemaduras con la esperada primero.
        """
        # Arrange
        excel = generar_staging(tmp_path / "excel", "excel", contrato)

        # Act: filas de cada caso
        diagnosticos = _de(_tabla(excel, "cie_10_diagnostico_definitivo"), excel.id("cie_sin_mapeo"))
        sustancias = _de(_tabla(excel, "abuso_sustancias"), excel.id("sustancia_repetida"))
        lesiones = _de(_tabla(excel, "tipo_violencia"), excel.id("lesiones"))
        mecanismo = _de(_tabla(excel, "examen_fisico"), excel.id("lesiones"))
        complicaciones = _de(_tabla(excel, "complicaciones_hospitalizacion"), excel.id("complicacion_sin_mapeo"))
        quemaduras = _de(_tabla(excel, "quemaduras"), excel.id("tomas"))

        # Assert: en CIE-10 y complicaciones, dos textos sin mapear distintos y uno repetido exacto
        sin_mapear = [f["cie_10_diagnostico_definitivo"] for f in diagnosticos if not f["cie10_mapeado"]]
        assert len(diagnosticos) == 4 and sorted(sin_mapear) == ["texto sin pareja 1", "texto sin pareja 1",
                                                                 "texto sin pareja 2"]
        assert [f["abuso_de_drogas"] for f in sustancias] == ["sustancia 1", "sustancia 1"]
        assert len(lesiones) == 2 and len(mecanismo) == 1
        sin_mapear = [f["cie_10_complicaciones_de_hospitalizacion"] for f in complicaciones
                      if not f["complicacion_cie10_mapeada"]]
        assert len(complicaciones) == 4 and len(set(sin_mapear)) == 2 and len(sin_mapear) == 3
        assert {f["lugar_de_complicacion"] for f in complicaciones} == {"lugar_de_complicacion 1"}
        assert [f["quemadura"] for f in quemaduras] == ["quemadura primera", "quemadura segunda"]

    def test_casos_propios_de_redcap(self, tmp_path, contrato):
        """
        Qué es: prueba unitaria de los casos de REDCap (lesión con mecanismo por fila y código CIE-10 repetido).
        Qué hace: genera el staging de REDCap y revisa las lesiones y los diagnósticos de las atenciones del caso.
        Esperado: tres lesiones, una sin mecanismo (el puente la carga con el miembro 'Sin dato') y dos idénticas
                  (las dos se cargan); el mismo código CIE-10 dos veces en el diagnóstico (queda uno y un
                  duplicado).
        """
        # Arrange
        redcap = generar_staging(tmp_path / "redcap", "redcap", contrato)

        # Act
        lesiones = _de(_tabla(redcap, "examen_fisico"), redcap.id("lesiones"))
        diagnosticos = _de(_tabla(redcap, "cie_10_diagnosticos"), redcap.id("cie_sin_mapeo"))

        # Assert
        assert len(lesiones) == 3
        assert sum(f["mecanismo_primario"] is None for f in lesiones) == 1
        assert lesiones[0] == lesiones[2]
        assert [f["cie_10_diagnostico_definitivo"] for f in diagnosticos] == ["CIE SINTETICO 1", "CIE SINTETICO 1"]


class TestStagingSinteticoValidez:
    def test_valores_dentro_de_rango_y_fechas_en_orden(self, staging):
        """
        Qué es: prueba unitaria de que el staging sintético es válido por construcción (base de las verificaciones de
                valores de la bodega, QR-DOM y QR-CON).
        Qué hace: recorre las columnas numéricas con rango de la transformación y las fechas de llegada, hospitalización y
                  alta de cada atención.
        Esperado: ningún valor fuera de su rango, presión diastólica menor o igual que la sistólica, días de UCI menores o
                  iguales que los de hospitalización y, por atención, el día de llegada no posterior al de hospitalización
                  ni este al del alta.
        """
        # Arrange: tablas sintéticas de la fuente
        tablas = {t: _tabla(staging, t) for t in
                  ("signos_vitales", "laboratorio", "puntuacion_de_severidad", "mecanismo_de_lesion", "liquidos",
                   "hospitalizacion", "uci", "informacion_demografica")}

        # Act: valores fuera de rango, por (tabla, columna)
        fuera = {}
        for tabla, filas in tablas.items():
            for columna, (minimo, maximo) in RANGOS_VALIDOS.items():
                malos = [f[columna] for f in filas if f.get(columna) is not None and not minimo <= f[columna] <= maximo]
                if malos:
                    fuera[(tabla, columna)] = malos

        # Assert
        assert fuera == {}
        assert all(f["presion_arterial_diastolica"] <= f["presion_arterial_sistolica"] for f in tablas["signos_vitales"]
                   if None not in (f["presion_arterial_diastolica"], f["presion_arterial_sistolica"]))
        uci = {f[CLAVE_ATENCION]: f["dias_usados_uci"] for f in tablas["uci"]}
        assert all(uci[f[CLAVE_ATENCION]] <= f["dias_de_hospitalizacion"] for f in tablas["hospitalizacion"]
                   if None not in (uci.get(f[CLAVE_ATENCION]), f["dias_de_hospitalizacion"]))
        llegada = {f[CLAVE_ATENCION]: f["fecha_y_hora_de_llegada_del_paciente"] for f in tablas["informacion_demografica"]}
        for f in tablas["hospitalizacion"]:
            fechas = [llegada.get(f[CLAVE_ATENCION]), f["fecha_de_admision"], f["fecha_y_hora_de_alta"]]
            if None not in fechas:
                assert fechas[0].date() <= fechas[1].date() <= fechas[2].date(), f[CLAVE_ATENCION]
