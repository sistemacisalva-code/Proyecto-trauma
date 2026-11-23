import pandas as pd
import pytest

from etl.transform.redcap.consolidacion import consolidar_particiones

COLUMNAS = ["record_id", "redcap_repeat_instrument", "redcap_repeat_instance", "dato"]
PARTICION_ANTIGUA = "2026-09-29T115813"
PARTICION_NUEVA = "2026-10-03T101500"


def _df(filas, columnas=COLUMNAS):
    return pd.DataFrame(filas, columns=columnas)


@pytest.fixture
def particiones_sinteticas():
    """
    Crea dos particiones incrementales sintéticas (sin datos reales), con valores ficticios:
    - antigua: registro "1" con dos instancias repetibles, registro "2" con una fila.
    - nueva: registro "1" modificado (llega completo, ya sin la instancia 2) y registro "3" nuevo.
    Son DataFrames en memoria, aislados de data/raw y de cualquier otra prueba.
    """
    return {
        PARTICION_ANTIGUA: _df([
            ["1", "dx", "1", "a1"],
            ["1", "dx", "2", "a2"],
            ["2", None, None, "b1"],
        ]),
        PARTICION_NUEVA: _df([
            ["1", "dx", "1", "a1_nuevo"],
            ["3", None, None, "c1"],
        ]),
    }


class TestConsolidarParticionesReemplazo:
    def test_registro_modificado_se_reemplaza_completo(self, particiones_sinteticas):
        """
        Qué es: prueba unitaria de consolidar_particiones (reemplazo por registro).
        Qué hace: consolida una partición antigua y una nueva donde el registro "1" llega modificado
                  y sin una de sus dos instancias repetibles.
        Esperado: el registro "1" queda solo con la fila de la partición nueva; la instancia borrada
                  y la versión antigua de la fila desaparecen.
        """
        # Arrange: el fixture trae el registro "1" con 2 filas (antigua) y 1 fila modificada (nueva)

        # Act: consolidar
        foto, _ = consolidar_particiones(particiones_sinteticas)

        # Assert: el registro se reemplaza completo (no fila por fila), por eso la instancia 2 no sobrevive
        registro_1 = foto[foto["record_id"] == "1"]
        assert registro_1["dato"].tolist() == ["a1_nuevo"]

    def test_registro_sin_cambios_conserva_su_version(self, particiones_sinteticas):
        """
        Qué es: prueba unitaria de consolidar_particiones (registros no modificados).
        Qué hace: consolida las particiones del fixture y consulta el registro "2", que solo existe
                  en la partición antigua.
        Esperado: el registro "2" se conserva con su valor original.
        """
        # Arrange: el registro "2" aparece únicamente en la partición antigua

        # Act: consolidar
        foto, _ = consolidar_particiones(particiones_sinteticas)

        # Assert: nada lo reemplaza, por lo que debe permanecer intacto
        assert foto.loc[foto["record_id"] == "2", "dato"].tolist() == ["b1"]

    def test_registro_nuevo_se_agrega(self, particiones_sinteticas):
        """
        Qué es: prueba unitaria de consolidar_particiones (registros nuevos).
        Qué hace: consolida las particiones del fixture y consulta el registro "3", que solo existe
                  en la partición nueva.
        Esperado: la foto contiene los tres registros ("1", "2" y "3").
        """
        # Arrange: el registro "3" aparece únicamente en la partición nueva

        # Act: consolidar
        foto, _ = consolidar_particiones(particiones_sinteticas)

        # Assert: la foto es la unión de todos los registros vigentes
        assert set(foto["record_id"]) == {"1", "2", "3"}

    def test_salida_sin_columna_auxiliar_y_con_indice_reiniciado(self, particiones_sinteticas):
        """
        Qué es: prueba unitaria del contrato de salida de consolidar_particiones.
        Qué hace: consolida las particiones del fixture e inspecciona columnas e índice.
        Esperado: no queda la columna auxiliar "_particion", las columnas son las del export
                  y el índice es 0..n-1 (los bloques posteriores dependen de un índice limpio).
        """
        # Arrange: el fixture; la consolidación marca internamente cada fila con su partición

        # Act: consolidar
        foto, _ = consolidar_particiones(particiones_sinteticas)

        # Assert: la marca interna no debe filtrarse al resto del pipeline y el índice debe reiniciarse
        assert "_particion" not in foto.columns
        assert list(foto.columns) == COLUMNAS
        assert list(foto.index) == list(range(len(foto)))


class TestConsolidarParticionesResumen:
    def test_resumen_cuenta_filas_y_registros(self, particiones_sinteticas):
        """
        Qué es: prueba unitaria del resumen de conteos de consolidar_particiones.
        Qué hace: consolida las particiones del fixture y lee el resumen devuelto.
        Esperado: 2 particiones leídas, 5 filas totales, 3 vigentes y 2 reemplazadas, 3 record_id
                  distintos y 1 registro presente en más de una partición.
        """
        # Arrange: antigua = 3 filas (registros 1, 1, 2); nueva = 2 filas (registros 1, 3)

        # Act: consolidar
        _, resumen = consolidar_particiones(particiones_sinteticas)

        # Assert: el resumen es la evidencia de trazabilidad que se guarda en el reporte de calidad
        assert resumen["particiones_leidas"] == 2
        assert resumen["particiones_vacias_omitidas"] == 0
        assert resumen["filas_totales"] == 5
        assert resumen["filas_vigentes"] == 3
        assert resumen["filas_reemplazadas"] == 2
        assert resumen["record_id_distintos"] == 3
        assert resumen["record_id_en_mas_de_una_particion"] == 1


class TestConsolidarParticionesValidaciones:
    def test_sin_particiones_lanza_valueerror(self):
        """
        Qué es: prueba unitaria de validación de entrada de consolidar_particiones.
        Qué hace: consolida un diccionario vacío.
        Esperado: lanza ValueError; no hay nada que transformar.
        """
        # Arrange: ninguna partición

        # Act + Assert: debe detenerse con un error claro, no devolver una foto vacía
        with pytest.raises(ValueError):
            consolidar_particiones({})

    def test_particion_vacia_se_omite_y_se_cuenta(self, particiones_sinteticas):
        """
        Qué es: prueba unitaria del manejo de extracciones sin cambios.
        Qué hace: agrega una partición vacía (pd.DataFrame([]), sin columnas) a las del fixture.
        Esperado: no falla por esquema, la foto es igual a la de las dos particiones originales
                  y el resumen cuenta 1 partición vacía omitida (3 leídas).
        """
        # Arrange: una corrida sin cambios produce un DataFrame sin columnas; no es deriva de esquema
        sin_vacia, _ = consolidar_particiones(particiones_sinteticas)
        con_vacia = {**particiones_sinteticas, "2026-10-04T090000": pd.DataFrame([])}

        # Act: consolidar con la partición vacía incluida
        foto, resumen = consolidar_particiones(con_vacia)

        # Assert: la partición vacía no altera la foto y queda registrada en el resumen
        pd.testing.assert_frame_equal(foto, sin_vacia)
        assert resumen["particiones_vacias_omitidas"] == 1
        assert resumen["particiones_leidas"] == 3

    def test_todas_vacias_lanza_valueerror(self):
        """
        Qué es: prueba unitaria de validación de entrada de consolidar_particiones.
        Qué hace: consolida únicamente particiones vacías.
        Esperado: lanza ValueError, porque no hay datos que transformar.
        """
        # Arrange: dos corridas sin cambios y ninguna con datos
        particiones = {PARTICION_ANTIGUA: pd.DataFrame([]), PARTICION_NUEVA: pd.DataFrame([])}

        # Act + Assert: debe detenerse en lugar de producir una foto sin columnas
        with pytest.raises(ValueError):
            consolidar_particiones(particiones)

    def test_esquema_distinto_lanza_valueerror(self, particiones_sinteticas):
        """
        Qué es: prueba unitaria del control de deriva de esquema entre particiones.
        Qué hace: agrega a la partición nueva una columna que la antigua no tiene.
        Esperado: lanza ValueError (posible cambio en el proyecto REDCap).
        """
        # Arrange: la partición nueva trae una columna adicional
        particiones_sinteticas[PARTICION_NUEVA] = particiones_sinteticas[PARTICION_NUEVA].assign(extra="x")

        # Act + Assert: un cambio de esquema debe detener el pipeline, no propagarse
        with pytest.raises(ValueError):
            consolidar_particiones(particiones_sinteticas)

    def test_record_id_nulo_lanza_valueerror(self):
        """
        Qué es: prueba unitaria de validación de datos de consolidar_particiones.
        Qué hace: consolida una partición donde una fila no tiene record_id.
        Esperado: lanza ValueError; groupby descartaría esa fila en silencio.
        """
        # Arrange: una fila sin identificador de registro
        particiones = {PARTICION_ANTIGUA: _df([["1", None, None, "a1"], [None, None, None, "x"]])}

        # Act + Assert: debe detenerse antes de perder la fila sin aviso
        with pytest.raises(ValueError):
            consolidar_particiones(particiones)


class TestConsolidarParticionesOrden:
    def test_orden_cronologico_no_depende_del_orden_del_diccionario(self, particiones_sinteticas):
        """
        Qué es: prueba unitaria de la determinación de la partición más reciente.
        Qué hace: consolida las mismas particiones con las claves del diccionario en orden invertido.
        Esperado: la foto es idéntica a la del orden normal; gana la partición de nombre mayor.
        """
        # Arrange: el diccionario con la partición nueva insertada primero
        esperado, _ = consolidar_particiones(particiones_sinteticas)
        invertido = {
            PARTICION_NUEVA: particiones_sinteticas[PARTICION_NUEVA],
            PARTICION_ANTIGUA: particiones_sinteticas[PARTICION_ANTIGUA],
        }

        # Act: consolidar
        foto, _ = consolidar_particiones(invertido)

        # Assert: el resultado depende del nombre (fecha) de la partición, no de cómo se armó el diccionario
        pd.testing.assert_frame_equal(foto.sort_values(COLUMNAS).reset_index(drop=True),
                                      esperado.sort_values(COLUMNAS).reset_index(drop=True))

    def test_columnas_en_distinto_orden_se_alinean(self, particiones_sinteticas):
        """
        Qué es: prueba unitaria de la alineación de columnas entre particiones.
        Qué hace: invierte el orden de las columnas de la partición nueva y consolida.
        Esperado: no falla y la foto conserva el orden de columnas de la primera partición.
        """
        # Arrange: mismas columnas pero en orden inverso en la partición nueva
        nueva = particiones_sinteticas[PARTICION_NUEVA]
        particiones_sinteticas[PARTICION_NUEVA] = nueva[list(reversed(COLUMNAS))]

        # Act: consolidar
        foto, _ = consolidar_particiones(particiones_sinteticas)

        # Assert: el orden original del export se preserva (lo necesita la división por *_complete)
        assert list(foto.columns) == COLUMNAS
