import pandas as pd
import pytest

from etl.transform.common.keys import (
    COL_ORIGEN,
    COL_SISTEMA,
    COL_TRAUMA,
    aplicar_llaves,
    construir_trauma_register_id,
    validar_grano,
)

TABLA_BASE = "informacion_demografica"


@pytest.fixture
def tablas():
    """
    Salida sintética de un transformer: una tabla base (un episodio por fila) y una hija con dos
    filas del episodio "1" y una del "2". Los ids y valores son inventados.
    """
    return {
        TABLA_BASE: pd.DataFrame({"record_id": ["1", "2"], "genero": ["M", "F"]}),
        "signos_vitales": pd.DataFrame({"record_id": ["1", "1", "2"], "frecuencia_cardiaca": [80, 90, 70]}),
    }


class TestKeysGrano:
    def test_clave_unica_y_completa_no_falla(self):
        """
        Qué es: prueba unitaria de validar_grano (caso normal).
        Qué hace: valida una clave sin nulos ni repetidos.
        Esperado: no lanza ninguna excepción.
        """
        # Arrange: tres episodios distintos
        df = pd.DataFrame({"record_id": ["1", "2", "3"]})

        # Act + Assert: no lanza (si lanzara, la prueba falla sola)
        validar_grano(df, ["record_id"], TABLA_BASE)

    def test_clave_con_nulos_falla(self):
        """
        Qué es: prueba unitaria de validar_grano ante una clave nula.
        Qué hace: valida una clave con un valor nulo.
        Esperado: ValueError que nombra la tabla y dice que hay nulos.
        """
        # Arrange: un episodio sin identificador
        df = pd.DataFrame({"record_id": ["1", None]})

        # Act + Assert: se detiene, un nulo no puede identificar un episodio
        with pytest.raises(ValueError, match=f"{TABLA_BASE}.*nulos"):
            validar_grano(df, ["record_id"], TABLA_BASE)

    def test_clave_repetida_falla(self):
        """
        Qué es: prueba unitaria de validar_grano ante un grano duplicado.
        Qué hace: valida una clave con un valor repetido.
        Esperado: ValueError que dice que la clave no es única.
        """
        # Arrange: el episodio "1" aparece dos veces
        df = pd.DataFrame({"record_id": ["1", "1", "2"]})

        # Act + Assert: se detiene, el grano debe ser un episodio por fila
        with pytest.raises(ValueError, match="no es única"):
            validar_grano(df, ["record_id"], TABLA_BASE)


class TestKeysConstruirTraumaRegisterId:
    @pytest.mark.parametrize("fuente, esperado", [("redcap", "RC-12"), ("excel_historico", "EX-12")])
    def test_prefijo_segun_la_fuente(self, fuente, esperado):
        """
        Qué es: prueba unitaria de construir_trauma_register_id (prefijo por fuente).
        Qué hace: construye la llave del id "12" para REDCap y para el Excel histórico.
        Esperado: "RC-12" y "EX-12": el prefijo evita que dos fuentes colisionen.
        """
        # Arrange: un id numérico como texto
        ids = pd.Series(["12"])

        # Act: construir la llave
        llave = construir_trauma_register_id(fuente, ids)

        # Assert: prefijo de la fuente más el id
        assert llave.tolist() == [esperado]

    def test_acepta_ids_numericos_y_no_modifica_la_entrada(self):
        """
        Qué es: prueba unitaria de construir_trauma_register_id con ids enteros.
        Qué hace: construye la llave de una serie de enteros.
        Esperado: "RC-1" y "RC-2"; la serie original sigue siendo de enteros.
        """
        # Arrange: ids como enteros
        ids = pd.Series([1, 2])

        # Act: construir la llave
        llave = construir_trauma_register_id("redcap", ids)

        # Assert: llave en texto y entrada intacta
        assert llave.tolist() == ["RC-1", "RC-2"]
        assert ids.tolist() == [1, 2]

    def test_fuente_desconocida_falla(self):
        """
        Qué es: prueba unitaria de construir_trauma_register_id con una fuente sin prefijo.
        Qué hace: pide la llave para una fuente que no está registrada.
        Esperado: ValueError que nombra la fuente.
        """
        # Arrange: fuente inexistente
        ids = pd.Series(["1"])

        # Act + Assert: se detiene en lugar de inventar un prefijo
        with pytest.raises(ValueError, match="otra_fuente"):
            construir_trauma_register_id("otra_fuente", ids)

    @pytest.mark.parametrize("ids", [["1", None], ["1", ""]])
    def test_ids_nulos_o_vacios_fallan(self, ids):
        """
        Qué es: prueba unitaria de construir_trauma_register_id con identificadores ausentes.
        Qué hace: construye la llave de una serie con un nulo y con una cadena vacía (2 casos).
        Esperado: ValueError en ambos casos: "RC-" no identifica ningún episodio.
        """
        # Arrange: una serie con un id ausente
        serie = pd.Series(ids)

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="nulos o vacíos"):
            construir_trauma_register_id("redcap", serie)


class TestKeysAplicarLlaves:
    def test_tabla_base_lleva_las_tres_columnas_de_llave(self, tablas, reporte):
        """
        Qué es: prueba unitaria de aplicar_llaves sobre la tabla base.
        Qué hace: aplica las llaves de REDCap a la salida sintética.
        Esperado: la base empieza por trauma_register_id, source_record_id y source_system, ya no tiene
                  record_id y conserva el id original sin modificar.
        """
        # Arrange: salida sintética del fixture

        # Act: aplicar las llaves
        salida = aplicar_llaves(tablas, "redcap", TABLA_BASE, reporte)

        # Assert: orden y contenido de las columnas de llave
        base = salida[TABLA_BASE]
        assert list(base.columns) == [COL_TRAUMA, COL_ORIGEN, COL_SISTEMA, "genero"]
        assert base[COL_TRAUMA].tolist() == ["RC-1", "RC-2"]
        assert base[COL_ORIGEN].tolist() == ["1", "2"]
        assert (base[COL_SISTEMA] == "redcap").all()

    def test_tablas_hijas_solo_llevan_la_llave_hacia_el_hecho(self, tablas, reporte):
        """
        Qué es: prueba unitaria de aplicar_llaves sobre una tabla hija.
        Qué hace: aplica las llaves y revisa las columnas de la tabla de signos vitales.
        Esperado: solo trauma_register_id (primera columna) y sus datos; sin source_record_id ni source_system.
        """
        # Arrange: salida sintética del fixture

        # Act: aplicar las llaves
        salida = aplicar_llaves(tablas, "redcap", TABLA_BASE, reporte)

        # Assert: la hija se enlaza por la llave natural y conserva sus filas
        hija = salida["signos_vitales"]
        assert list(hija.columns) == [COL_TRAUMA, "frecuencia_cardiaca"]
        assert hija[COL_TRAUMA].tolist() == ["RC-1", "RC-1", "RC-2"]

    def test_filas_huerfanas_se_cuentan_y_no_se_eliminan(self, tablas, reporte):
        """
        Qué es: prueba unitaria de la regla de filas hijas sin episodio.
        Qué hace: agrega a la tabla hija una fila del episodio "9", que no existe en la base, y aplica las llaves.
        Esperado: la fila se conserva y la regla reporta 4 evaluables y 1 que incumple.
        """
        # Arrange: una fila huérfana
        tablas["signos_vitales"] = pd.concat(
            [tablas["signos_vitales"], pd.DataFrame({"record_id": ["9"], "frecuencia_cardiaca": [60]})],
            ignore_index=True,
        )

        # Act: aplicar las llaves
        salida = aplicar_llaves(tablas, "redcap", TABLA_BASE, reporte)

        # Assert: no se pierde información y la huérfana queda cuantificada
        assert len(salida["signos_vitales"]) == 4
        regla = reporte.reglas[("signos_vitales", f"filas sin episodio en la tabla base ({TABLA_BASE})")]
        assert (regla["filas_evaluables"], regla["filas_que_incumplen"]) == (4, 1)

    def test_no_modifica_las_tablas_de_entrada(self, tablas, reporte):
        """
        Qué es: prueba unitaria de que aplicar_llaves no tiene efectos secundarios.
        Qué hace: aplica las llaves y compara las tablas de entrada con una copia hecha antes.
        Esperado: las tablas originales conservan record_id y no ganan columnas.
        """
        # Arrange: copia de referencia
        copia = {nombre: df.copy() for nombre, df in tablas.items()}

        # Act: aplicar las llaves
        aplicar_llaves(tablas, "redcap", TABLA_BASE, reporte)

        # Assert: entrada intacta
        for nombre in tablas:
            pd.testing.assert_frame_equal(tablas[nombre], copia[nombre])

    def test_falta_la_tabla_base(self, tablas, reporte):
        """
        Qué es: prueba unitaria de aplicar_llaves sin tabla base.
        Qué hace: pide aplicar las llaves indicando una tabla base que no está en la salida.
        Esperado: KeyError que nombra la tabla.
        """
        # Arrange: nombre de tabla base inexistente

        # Act + Assert: se detiene, sin base no hay episodios contra los que enlazar
        with pytest.raises(KeyError, match="tabla_inexistente"):
            aplicar_llaves(tablas, "redcap", "tabla_inexistente", reporte)

    def test_grano_duplicado_en_la_base_falla(self, tablas, reporte):
        """
        Qué es: prueba unitaria de aplicar_llaves con un episodio repetido en la tabla base.
        Qué hace: duplica un record_id en la base y aplica las llaves.
        Esperado: ValueError por clave no única.
        """
        # Arrange: el episodio "1" repetido en la base
        tablas[TABLA_BASE] = pd.DataFrame({"record_id": ["1", "1"], "genero": ["M", "F"]})

        # Act + Assert: se detiene antes de generar llaves ambiguas
        with pytest.raises(ValueError, match="no es única"):
            aplicar_llaves(tablas, "redcap", TABLA_BASE, reporte)
