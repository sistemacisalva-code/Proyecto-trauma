from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from etl.load.warehouse.completo_loader import CompletoLoader
from etl.load.warehouse.contrato import CLAVE_ATENCION, leer_contrato
from etl.load.warehouse.cuarentena import COLUMNA_REGLA
from etl.load.warehouse.por_contrato import REGLA_FECHA, REGLA_HUERFANA
from etl.load.warehouse.resolucion import (
    NO_APLICA, SIN_DATO, combinaciones, filas_de_puente, marco_del_hecho, primera_toma, texto_sin_mapeo,
)
from etl.load.warehouse.staging import leer_tablas
from tests.fixtures.staging_sintetico import generar_staging

K = CLAVE_ATENCION
CONTRATO_COMPLETO = Path(__file__).resolve().parents[2] / "config" / "contratos" / "completo.yaml"
T = datetime(2022, 5, 10, 8, 0)


def _o(excel, redcap) -> dict:
    return {"excel": excel, "redcap": redcap}


@pytest.fixture
def signos():
    """
    Tomas sintéticas de dos atenciones (A con cuatro tomas: una sin valores, una sin fecha y dos con fecha en
    orden inverso; B con una sola). Valores inventados, sin datos de pacientes.
    """
    return pd.DataFrame({
        K: ["A", "A", "A", "A", "B"],
        "fecha": [T.replace(hour=11), T, None, T.replace(hour=9), T],
        "pulso": [110.0, None, 70.0, 90.0, 80.0],
        "avup": [None, None, None, "Alerta", None],
    })


class TestResolucionPrimeraToma:
    def test_elige_la_primera_con_valor_y_cuenta_las_demas(self, signos):
        """
        Qué es: prueba unitaria de primera_toma (regla de la primera toma).
        Qué hace: elige una toma por atención entre tomas desordenadas, una sin valores y una sin fecha.
        Esperado: A toma la de las 09:00 (la de las 08:00 no tiene valores; la sin fecha va al final), con su pulso y
                  su AVUP de la misma fila; B su única toma; conteos 2 cargadas, 2 otra_toma y 1 sin_valor.
        """
        # Arrange: columnas de valor de la tabla (sin la clave ni el orden)
        columnas = ["pulso", "avup"]

        # Act
        elegidas, conteo = primera_toma(signos, columnas, ["fecha"])

        # Assert: una fila por atención, sin mezclar tomas
        a = elegidas[elegidas[K] == "A"].iloc[0]
        assert (a["pulso"], a["avup"]) == (90.0, "Alerta")
        assert elegidas[elegidas[K] == "B"]["pulso"].tolist() == [80.0]
        assert conteo == {"cargadas": 2, "otra_toma": 2, "sin_valor": 1}

    def test_sin_orden_gana_el_orden_del_staging(self, signos):
        """
        Qué es: prueba unitaria de primera_toma sin columna de orden (hojas hijas del Excel).
        Qué hace: elige una toma por atención sin indicar orden.
        Esperado: en A gana la primera fila del staging con valores (pulso 110), aunque no sea la más temprana.
        """
        # Arrange: no aplica, se usan las tomas del fixture

        # Act
        elegidas, _ = primera_toma(signos, ["pulso", "avup"], [])

        # Assert
        assert elegidas[elegidas[K] == "A"]["pulso"].tolist() == [110.0]


class TestResolucionMarcoDelHecho:
    def test_une_grano_atencion_y_primera_toma_con_conteos(self, signos):
        """
        Qué es: prueba unitaria de marco_del_hecho (una fila por atención para el hecho y sus dimensiones).
        Qué hace: arma el marco con una tabla de grano atención (también filas del hecho, con la clave como origen)
                  y la tabla de tomas.
        Esperado: dos filas con columnas 'tabla.columna' (incluida la clave como origen), el pulso de la primera toma
                  y el conteo de cada tabla como uso del hecho.
        """
        # Arrange: tablas y grano declarados
        tablas = {"registro": pd.DataFrame({K: ["A", "B"], "genero": ["genero 1", None]}), "signos": signos}
        declaradas = {"registro": {"grano": "atencion"},
                      "signos": {"grano": "varias", "toma": "primera", "orden": ["fecha"]}}
        origenes = {"registro.trauma_register_id", "registro.genero", "signos.pulso"}

        # Act
        marco, conteos = marco_del_hecho(tablas, "registro", origenes, declaradas)

        # Assert
        assert marco["registro.trauma_register_id"].tolist() == ["A", "B"]
        assert marco["signos.pulso"].tolist() == [90.0, 80.0]
        assert conteos == {"registro": {"cargadas": 2}, "signos": {"cargadas": 2, "otra_toma": 2, "sin_valor": 1}}

    def test_grano_atencion_repetido_se_rechaza(self):
        """
        Qué es: prueba unitaria de la confirmación del grano al leer.
        Qué hace: arma el marco con una tabla declarada de grano atención que repite una atención.
        Esperado: ValueError que nombra la tabla; la carga no sigue con un grano falso.
        """
        # Arrange: la atención A aparece dos veces
        tablas = {"registro": pd.DataFrame({K: ["A", "A"]})}

        # Act + Assert
        with pytest.raises(ValueError, match="registro"):
            marco_del_hecho(tablas, "registro", set(), {"registro": {"grano": "atencion"}})


class TestResolucionCombinaciones:
    def test_atributo_vacio_es_sin_dato_y_grupo_vacio_no_aplica(self):
        """
        Qué es: prueba unitaria de combinaciones (miembros por defecto).
        Qué hace: arma una dimensión de mecanismo (vacio: no_aplica) con un atributo de texto y uno numérico, para
                  una fila completa, una con el texto vacío y una sin nada; y la misma con vacio: sin_dato.
        Esperado: el texto vacío es 'Sin dato'; la fila sin nada es 'No aplica' (texto) con el número en NULL; con
                  sin_dato, esa fila es 'Sin dato'. Un atributo que la fuente no trae (None) es 'Sin dato'.
        """
        # Arrange: tres filas y un atributo sin origen en la fuente
        marco = pd.DataFrame({"t.caida": ["caida 1", None, None], "t.altura": [2.0, 3.0, None]})
        atributos = {"caida": "t.caida", "altura": "t.altura", "superficie": None}

        # Act
        no_aplica = combinaciones(marco, atributos, {"caida", "superficie"}, "no_aplica")
        sin_dato = combinaciones(marco, atributos, {"caida", "superficie"})

        # Assert
        assert no_aplica.iloc[0].tolist() == ["caida 1", 2.0, SIN_DATO]
        assert no_aplica.iloc[1].tolist() == [SIN_DATO, 3.0, SIN_DATO]
        assert no_aplica.iloc[2].tolist() == [NO_APLICA, None, NO_APLICA]
        assert sin_dato.iloc[2].tolist() == [SIN_DATO, None, SIN_DATO]


class TestResolucionFilasDePuente:
    def test_sin_valor_consulta_por_atencion_y_secuencia(self):
        """
        Qué es: prueba unitaria de filas_de_puente con una tabla de consulta (patrón de las lesiones del Excel).
        Qué hace: arma el bloque con tres filas de lesiones (una sin valores) y el mecanismo de la atención en otra
                  tabla de grano atención, que también tiene una atención sin lesiones.
        Esperado: dos filas con el mecanismo copiado y secuencia 1 y 2; la fila vacía cuenta como sin_valor; en la
                  tabla de consulta, 1 fila usada y 1 sin uso (sin_valor).
        """
        # Arrange: bloque de puente sintético con secuencia y una columna de la tabla de consulta
        tablas = {
            "lesiones": pd.DataFrame({K: ["A", "A", "A"], "parte": ["parte 1", None, "parte 2"]}),
            "examen": pd.DataFrame({K: ["A", "B"], "mecanismo": ["mecanismo 1", "mecanismo 2"]}),
        }
        bloque = {"filas": _o("lesiones", None), "columnas": {
            "secuencia": {"resolucion": "secuencia"},
            "parte_id": {"resolucion": "dimension", "dimension": "dim_parte", "origen": _o("lesiones.parte", None)},
            "mecanismo_id": {"resolucion": "dimension", "dimension": "dim_mec", "origen": _o("examen.mecanismo", None)},
        }}
        catalogos = {"dim_parte": {"tipo": "catalogo"}, "dim_mec": {"tipo": "catalogo"}}

        # Act
        filas, tabla_filas, conteos = filas_de_puente(tablas, bloque, "excel", catalogos)

        # Assert
        assert tabla_filas == "lesiones"
        assert filas[["lesiones.parte", "examen.mecanismo", "secuencia"]].values.tolist() == [
            ["parte 1", "mecanismo 1", 1], ["parte 2", "mecanismo 1", 2]]
        assert conteos == {"lesiones": {"sin_valor": 1}, "examen": {"cargadas": 1, "sin_valor": 1}}

    def test_las_filas_solo_traen_atenciones_de_la_tabla_de_filas(self):
        """
        Qué es: prueba unitaria de filas_de_puente (no inventa atenciones; sostiene la comprobación de _huellas).
        Qué hace: arma el bloque con una tabla de consulta que trae una atención (C) que no tiene filas en la tabla
                  de filas.
        Esperado: las atenciones del resultado son un subconjunto de las de la tabla de filas; C no aparece.
        """
        # Arrange: la consulta tiene una atención más que la tabla de filas
        tablas = {
            "lesiones": pd.DataFrame({K: ["A", "B"], "parte": ["parte 1", "parte 2"]}),
            "examen": pd.DataFrame({K: ["A", "B", "C"], "mecanismo": ["m 1", "m 2", "m 3"]}),
        }
        bloque = {"filas": _o("lesiones", None), "columnas": {
            "parte_id": {"resolucion": "dimension", "dimension": "dim_parte", "origen": _o("lesiones.parte", None)},
            "mecanismo_id": {"resolucion": "dimension", "dimension": "dim_mec", "origen": _o("examen.mecanismo", None)},
        }}
        catalogos = {"dim_parte": {"tipo": "catalogo"}, "dim_mec": {"tipo": "catalogo"}}

        # Act
        filas, _, conteos = filas_de_puente(tablas, bloque, "excel", catalogos)

        # Assert
        assert set(filas[K]) <= set(tablas["lesiones"][K]) and "C" not in set(filas[K])
        assert conteos["examen"] == {"cargadas": 2, "sin_valor": 1}

    def test_fuente_sin_filas_devuelve_none_y_texto_sin_mapeo(self):
        """
        Qué es: prueba unitaria de filas_de_puente sin filas en la fuente y de texto_sin_mapeo.
        Qué hace: pide el bloque en REDCap (filas null) y calcula texto_origen de tres códigos del Excel: uno mapeado
                  y dos sin pareja; y en una fuente sin bandera.
        Esperado: None para REDCap; el texto solo en las filas sin mapear; sin bandera, todo NULL.
        """
        # Arrange: códigos sintéticos y la columna de la que sale el texto
        bloque = {"filas": _o("codigos", None), "columnas": {"codigo_id": {
            "resolucion": "dimension", "dimension": "dim_codigo",
            "origen": _o("codigos.codigo", None), "mapeado": _o("codigos.mapeado", None)}}}
        filas = pd.DataFrame({"codigos.codigo": ["CIE SINTETICO 1", "texto 1", "texto 2"],
                              "codigos.mapeado": [True, False, False]})

        # Act
        redcap = filas_de_puente({}, bloque, "redcap", {})
        excel = texto_sin_mapeo(filas, bloque["columnas"]["codigo_id"], "excel")
        sin_bandera = texto_sin_mapeo(filas, bloque["columnas"]["codigo_id"], "redcap")

        # Assert
        assert redcap is None
        assert excel.tolist() == [None, "texto 1", "texto 2"]
        assert sin_bandera.isna().all()


class TestResolucionCuarentenaDelCompleto:
    @pytest.mark.parametrize("fuente", ["excel", "redcap"])
    def test_fecha_fuera_del_calendario_y_fila_huerfana(self, tmp_path, fuente):
        """
        Qué es: prueba unitaria de CompletoLoader.separar_cuarentena con el staging sintético (TC-CAR-05),
                sin base de datos.
        Qué hace: genera el staging de la fuente con el contrato real y separa la cuarentena.
        Esperado: la atención con la llegada antes del calendario sale completa, de todas sus tablas, con la regla
                  fecha_fuera_de_calendario; el procedimiento de una atención inexistente sale con fila_sin_atencion;
                  ninguna otra atención queda en cuarentena.
        """
        # Arrange: staging sintético y Loader sin engine (separar_cuarentena no usa la base)
        contrato = leer_contrato(str(CONTRATO_COMPLETO), "completo")
        casos = generar_staging(tmp_path / fuente, fuente, contrato)
        tablas = leer_tablas(str(casos.carpeta), contrato.columnas_por_tabla(fuente))
        loader = CompletoLoader(fuente=fuente, engine=None, staging_dir="", ruta_contrato="", quarantine_dir="",
                                hoy=date(2026, 10, 27))

        # Act
        quedan, cuarentena = loader.separar_cuarentena(tablas, contrato)

        # Assert: por tabla, las reglas y atenciones apartadas
        apartadas = pd.concat([df[[K, COLUMNA_REGLA]] for df in cuarentena.values() if len(df)])
        fuera, huerfana = casos.id("fuera_de_calendario"), casos.id("huerfana")
        assert set(apartadas[K]) == {fuera, huerfana}
        assert set(apartadas.loc[apartadas[K] == fuera, COLUMNA_REGLA]) == {REGLA_FECHA}
        assert apartadas.loc[apartadas[K] == huerfana, COLUMNA_REGLA].tolist() == [REGLA_HUERFANA]
        assert fuera not in set(quedan["informacion_demografica"][K])
        assert all(len(quedan[t]) + len(cuarentena[t]) == len(tablas[t]) for t in tablas)
