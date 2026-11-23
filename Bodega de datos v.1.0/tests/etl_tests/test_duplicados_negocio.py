"""
Pruebas del retiro de atenciones duplicadas por regla de negocio (etl/transform/common/duplicados_negocio.py).

Todas las tablas son sintéticas: llaves, documentos y fechas inventados, sin ningún dato de pacientes.
"""
import pandas as pd
import pytest

from etl.transform.base import BaseTransformer
from etl.transform.common.duplicados_negocio import MOTIVO, retirar_atenciones_duplicadas
from etl.transform.common.keys import COL_TRAUMA

TABLA_BASE = "informacion_demografica"
COLUMNAS = ("documento_seudonimo", "fecha_y_hora_de_llegada_del_paciente")
LLEGADA = pd.Timestamp("2024-03-10 08:30")
OTRA_LLEGADA = pd.Timestamp("2024-03-12 19:45")


def _base(filas: list[tuple]) -> pd.DataFrame:
    """Tabla base con la llave canónica: (id, documento, llegada, género, ocupación)."""
    return pd.DataFrame({
        COL_TRAUMA: [f[0] for f in filas], "source_record_id": [f[0][3:] for f in filas],
        "source_system": "redcap", COLUMNAS[0]: [f[1] for f in filas], COLUMNAS[1]: [f[2] for f in filas],
        "genero": [f[3] for f in filas], "ocupacion": [f[4] for f in filas],
    })


def _hija(ids: list[str]) -> pd.DataFrame:
    """Tabla hija con una fila por llave dada (valores distintos para poder seguir cada fila)."""
    return pd.DataFrame({COL_TRAUMA: ids, "frecuencia_cardiaca": [60 + i for i in range(len(ids))]})


def _retirar(base, hija, reporte):
    return retirar_atenciones_duplicadas({TABLA_BASE: base, "signos_vitales": hija}, TABLA_BASE, COLUMNAS, reporte)


class TestRetiroDeAtencionesDuplicadas:
    def test_conserva_la_que_mas_sabe_y_retira_la_otra_con_sus_hijas(self, reporte):
        """
        Qué es: prueba unitaria de retirar_atenciones_duplicadas (camino A) con una pareja repetida.
        Qué hace: dos atenciones con el mismo documento y la misma llegada; RC-1 tiene más celdas llenas que RC-2.
                  RC-1 tiene 1 fila hija y RC-2 tiene 2.
        Esperado: queda RC-1 (y la atención sin repetir RC-3); salen RC-2 y sus 2 filas hijas; el reporte registra la
                  atención retirada y las filas que salieron de cada tabla.
        """
        # Arrange: RC-1 sabe más de la atención (4 celdas contra 2 en la base, aunque tenga menos hijas)
        base = _base([("RC-1", "d1", LLEGADA, "genero 1", "ocupacion 1"), ("RC-2", "d1", LLEGADA, None, None),
                      ("RC-3", "d2", LLEGADA, "genero 2", None)])
        hija = _hija(["RC-1", "RC-2", "RC-2", "RC-3"])

        # Act
        salida = _retirar(base, hija, reporte)

        # Assert: sale el registro completo, el padre y las hijas
        assert salida[TABLA_BASE][COL_TRAUMA].tolist() == ["RC-1", "RC-3"]
        assert salida["signos_vitales"][COL_TRAUMA].tolist() == ["RC-1", "RC-3"]
        retirada = reporte.tabla("atenciones_descartadas").iloc[0]
        assert (retirada["trauma_register_id"], retirada["conservada"], retirada["motivo"]) == ("RC-2", "RC-1", MOTIVO)
        balance = reporte.tabla("balance_filas").set_index("tabla")
        assert (balance.loc[TABLA_BASE, "filas_entrada"], balance.loc[TABLA_BASE, "filas_salida"]) == (3, 2)
        assert (balance.loc["signos_vitales", "filas_entrada"], balance.loc["signos_vitales", "filas_salida"]) == (4, 2)

    def test_las_filas_de_las_atenciones_conservadas_no_cambian(self, reporte):
        """
        Qué es: prueba unitaria de la garantía del camino A: las hijas del padre que queda se conservan.
        Qué hace: retira un duplicado y compara, fila por fila, lo que tenían las atenciones conservadas antes y después.
        Esperado: las filas de RC-1 y RC-3 en la base y en la hija son idénticas, con sus mismos valores.
        """
        # Arrange: RC-1 con dos hijas, RC-3 con una, y RC-2 como duplicado de RC-1
        base = _base([("RC-1", "d1", LLEGADA, "genero 1", "ocupacion 1"), ("RC-2", "d1", LLEGADA, None, None),
                      ("RC-3", "d2", LLEGADA, "genero 2", None)])
        hija = _hija(["RC-1", "RC-1", "RC-2", "RC-3"])

        # Act
        salida = _retirar(base, hija, reporte)

        # Assert: mismas filas y mismos valores para las atenciones que se quedan
        conservadas = ["RC-1", "RC-3"]
        for nombre, original in ((TABLA_BASE, base), ("signos_vitales", hija)):
            esperado = original[original[COL_TRAUMA].isin(conservadas)].reset_index(drop=True)
            pd.testing.assert_frame_equal(salida[nombre], esperado)

    def test_las_filas_hijas_cuentan_para_elegir_la_que_se_conserva(self, reporte):
        """
        Qué es: prueba unitaria del criterio de elección (más información total, base más hijas).
        Qué hace: dos atenciones con la misma base; RC-2 tiene 3 filas hijas y RC-1 ninguna.
        Esperado: se conserva RC-2 y sale RC-1.
        """
        # Arrange: bases iguales de completas; solo las hijas desempatan
        base = _base([("RC-1", "d1", LLEGADA, "genero 1", None), ("RC-2", "d1", LLEGADA, "genero 1", None)])
        hija = _hija(["RC-2", "RC-2", "RC-2"])

        # Act
        salida = _retirar(base, hija, reporte)

        # Assert
        assert salida[TABLA_BASE][COL_TRAUMA].tolist() == ["RC-2"]
        assert len(salida["signos_vitales"]) == 3

    def test_el_empate_se_resuelve_con_la_menor_llave(self, reporte):
        """
        Qué es: prueba unitaria del desempate (misma información, sin depender del orden de las filas).
        Qué hace: dos atenciones idénticas en información, con la de mayor llave escrita primero.
        Esperado: se conserva RC-1, la de menor llave.
        """
        # Arrange: RC-9 aparece antes que RC-1 en la tabla
        base = _base([("RC-9", "d1", LLEGADA, "genero 1", None), ("RC-1", "d1", LLEGADA, "genero 1", None)])

        # Act
        salida = _retirar(base, _hija(["RC-9", "RC-1"]), reporte)

        # Assert
        assert salida[TABLA_BASE][COL_TRAUMA].tolist() == ["RC-1"]

    def test_un_grupo_de_tres_deja_una_sola_atencion(self, reporte):
        """
        Qué es: prueba unitaria de un grupo con más de dos atenciones repetidas.
        Qué hace: tres atenciones con el mismo documento y la misma llegada.
        Esperado: queda una; salen dos y el reporte registra ambas como retiradas del mismo grupo.
        """
        # Arrange
        base = _base([("RC-1", "d1", LLEGADA, "genero 1", "ocupacion 1"), ("RC-2", "d1", LLEGADA, "genero 1", None),
                      ("RC-3", "d1", LLEGADA, None, None)])

        # Act
        salida = _retirar(base, _hija(["RC-1", "RC-2", "RC-3"]), reporte)

        # Assert
        assert salida[TABLA_BASE][COL_TRAUMA].tolist() == ["RC-1"]
        retiradas = reporte.tabla("atenciones_descartadas")
        assert sorted(retiradas["trauma_register_id"]) == ["RC-2", "RC-3"]
        assert retiradas["grupo"].nunique() == 1


class TestRetiroDeAtencionesDuplicadasQueNoAplica:
    def test_llegadas_distintas_del_mismo_documento_no_son_duplicadas(self, reporte):
        """
        Qué es: prueba unitaria de dos llegadas distintas del mismo paciente (reingreso).
        Qué hace: dos atenciones con el mismo documento y fechas de llegada distintas.
        Esperado: las dos se conservan y no se registra ninguna atención retirada.
        """
        # Arrange
        base = _base([("RC-1", "d1", LLEGADA, "genero 1", None), ("RC-2", "d1", OTRA_LLEGADA, "genero 1", None)])
        hija = _hija(["RC-1", "RC-2"])

        # Act
        salida = _retirar(base, hija, reporte)

        # Assert
        assert salida[TABLA_BASE][COL_TRAUMA].tolist() == ["RC-1", "RC-2"]
        assert reporte.tabla("atenciones_descartadas").empty

    def test_documentos_vacios_no_se_cuentan_como_repetidos(self, reporte):
        """
        Qué es: prueba unitaria de pacientes sin documento (no identificados).
        Qué hace: dos atenciones con documento vacío y la misma llegada.
        Esperado: las dos se conservan: dos personas sin documento no son la misma.
        """
        # Arrange
        base = _base([("RC-1", None, LLEGADA, "genero 1", None), ("RC-2", None, LLEGADA, "genero 1", None)])

        # Act
        salida = _retirar(base, _hija(["RC-1", "RC-2"]), reporte)

        # Assert
        assert salida[TABLA_BASE][COL_TRAUMA].tolist() == ["RC-1", "RC-2"]

    def test_sin_repetidas_devuelve_las_mismas_tablas_y_no_registra_nada(self, reporte):
        """
        Qué es: prueba unitaria del caso sin atenciones duplicadas.
        Qué hace: aplica el retiro a tablas sin repetidas.
        Esperado: las mismas tablas, sin atenciones retiradas ni entradas nuevas en el balance.
        """
        # Arrange
        base = _base([("RC-1", "d1", LLEGADA, "genero 1", None), ("RC-2", "d2", LLEGADA, "genero 1", None)])
        hija = _hija(["RC-1", "RC-2"])

        # Act
        salida = _retirar(base, hija, reporte)

        # Assert
        assert salida[TABLA_BASE] is base and salida["signos_vitales"] is hija
        assert reporte.tabla("atenciones_descartadas").empty and reporte.tabla("balance_filas").empty

    def test_falta_una_columna_de_la_regla(self, reporte):
        """
        Qué es: prueba unitaria de la validación de columnas.
        Qué hace: pide el retiro con una columna que la base no tiene.
        Esperado: KeyError que nombra la columna; no se retira nada en silencio.
        """
        # Arrange: base sin la columna del documento
        base = _base([("RC-1", "d1", LLEGADA, "genero 1", None)]).drop(columns=COLUMNAS[0])

        # Act + Assert
        with pytest.raises(KeyError, match=COLUMNAS[0]):
            retirar_atenciones_duplicadas({TABLA_BASE: base}, TABLA_BASE, COLUMNAS, reporte)


class TestRetiroDeAtencionesDuplicadasEnLaTransformacion:
    def test_run_retira_el_duplicado_de_todas_las_tablas(self):
        """
        Qué es: prueba de integración del paso en BaseTransformer.run() (después de aplicar las llaves).
        Qué hace: ejecuta una fuente sintética con dos registros repetidos y una hija.
        Esperado: el resultado ya no trae el registro retirado ni sus hijas, y `rows` cuenta lo que quedó.
        """
        # Arrange: fuente mínima con record_id (la llave de la fuente) y un duplicado
        class FuenteSintetica(BaseTransformer):
            source_type = "redcap"
            source_system = "redcap"
            tabla_base = TABLA_BASE
            columnas_duplicado_negocio = COLUMNAS

            def transform(self, reporte):
                base = _base([("RC-1", "d1", LLEGADA, "genero 1", "ocupacion 1"), ("RC-2", "d1", LLEGADA, None, None)])
                base = base.drop(columns=[COL_TRAUMA, "source_record_id", "source_system"]).assign(record_id=["1", "2"])
                hija = _hija(["RC-1", "RC-2"]).drop(columns=COL_TRAUMA).assign(record_id=["1", "2"])
                return {TABLA_BASE: base, "signos_vitales": hija}

        # Act
        resultado = FuenteSintetica().run()

        # Assert
        assert resultado.tables[TABLA_BASE][COL_TRAUMA].tolist() == ["RC-1"]
        assert resultado.tables["signos_vitales"][COL_TRAUMA].tolist() == ["RC-1"]
        assert resultado.rows == {TABLA_BASE: 1, "signos_vitales": 1}
        assert len(resultado.reporte.tabla("atenciones_descartadas")) == 1
