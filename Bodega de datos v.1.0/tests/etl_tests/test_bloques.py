import pandas as pd
import pytest

from etl.transform.redcap.bloques import (
    INSTRUMENTOS_ESPERADOS,
    MARCADOR_VACIO,
    dividir_en_bloques,
    resumir_descartes,
)


@pytest.fixture
def export_con_marcadores():
    """
    Export REDCap ficticio y mínimo: 5 filas y los 15 instrumentos, cada uno con una columna de datos
    `dato_<instrumento>` y su marcador `<instrumento>_complete`. Todos los valores son inventados.

    Filas (las no mencionadas están vacías):
      A: episodio 1, fila principal: dato demográfico; UCI marcado "Complete" pero sin datos.
      B: episodio 2, fila principal: dato demográfico; UCI marcado "Incomplete" y sin datos.
      C: episodio 1, imagen repetible 1: dato y marcador "Complete" de imágenes.
      D: episodio 3, fila principal: dato y marcador "Complete" de UCI (sin dato demográfico).
      E: episodio 3, imagen repetible 1: totalmente vacía (ni dato ni marcador).
    """
    columnas = ["record_id", "redcap_repeat_instrument", "redcap_repeat_instance"]
    for nombre in INSTRUMENTOS_ESPERADOS:
        columnas += [f"dato_{nombre}", f"{nombre}_complete"]
    filas = [
        {"record_id": "1", "dato_informacion_demografica": "x", "uci_complete": "Complete"},
        {"record_id": "2", "dato_informacion_demografica": "x", "uci_complete": "Incomplete"},
        {"record_id": "1", "redcap_repeat_instrument": "imagenes", "redcap_repeat_instance": "1",
         "dato_imagenes": "RX", "imagenes_complete": "Complete"},
        {"record_id": "3", "dato_uci": "2", "uci_complete": "Complete"},
        {"record_id": "3", "redcap_repeat_instrument": "imagenes", "redcap_repeat_instance": "1"},
    ]
    return pd.DataFrame(filas, columns=columnas)


def _descartes_de(descartes: list[dict], instrumento: str) -> dict[str, int]:
    """{valor del marcador: filas descartadas} de un instrumento."""
    return {d["marcador"]: d["filas_descartadas"] for d in descartes if d["instrumento"] == instrumento}


class TestBloquesDescartes:
    def test_cuenta_las_filas_sin_datos_por_valor_del_marcador(self, export_con_marcadores):
        """
        Qué es: prueba unitaria de resumir_descartes (filas descartadas por no tener ningún dato del instrumento).
        Qué hace: cuenta las filas sin datos de UCI en el export sintético, separadas por el valor de uci_complete.
        Esperado: 1 con "Complete", 1 con "Incomplete" y 2 con marcador vacío; la fila D, que sí tiene dato de
                  UCI, no se cuenta.
        """
        # Arrange: export sintético del fixture

        # Act: resumir los descartes
        descartes = resumir_descartes(export_con_marcadores)

        # Assert: distribución por marcador; el vacío agrupa las filas de otros instrumentos (nulo estructural)
        assert _descartes_de(descartes, "uci") == {"Complete": 1, "Incomplete": 1, MARCADOR_VACIO: 2}

    def test_una_fila_con_datos_no_se_cuenta_aunque_tenga_marcador(self, export_con_marcadores):
        """
        Qué es: prueba unitaria de resumir_descartes sobre las filas conservadas.
        Qué hace: cuenta los descartes de imágenes, donde la fila C tiene dato y marcador "Complete".
        Esperado: solo 4 filas descartadas y todas con marcador vacío; el marcador de la fila conservada no aparece.
        """
        # Arrange: export sintético del fixture

        # Act: resumir los descartes
        descartes = resumir_descartes(export_con_marcadores)

        # Assert: las 4 filas sin imagen (A, B, D y E) no tienen marcador de imágenes
        assert _descartes_de(descartes, "imagenes") == {MARCADOR_VACIO: 4}

    def test_filas_del_bloque_mas_descartadas_igualan_las_filas_de_origen(self, export_con_marcadores):
        """
        Qué es: prueba de conservación de filas de la división en bloques, instrumento por instrumento.
        Qué hace: divide el export en bloques y suma, por instrumento, sus filas más las descartadas.
        Esperado: la suma es igual al número de filas del export (5) en los 15 instrumentos; ninguna fila
                  desaparece sin quedar contada.
        """
        # Arrange: export sintético del fixture
        df = export_con_marcadores

        # Act: dividir y resumir los descartes
        bloques = dividir_en_bloques(df)
        descartes = resumir_descartes(df)

        # Assert: conservación de filas por instrumento
        for nombre in INSTRUMENTOS_ESPERADOS:
            descartadas = sum(_descartes_de(descartes, nombre).values())
            assert len(bloques[nombre]) + descartadas == len(df), nombre

    def test_distingue_la_fila_principal_de_la_instancia_repetible(self, export_con_marcadores):
        """
        Qué es: prueba unitaria de la columna en_instancia_repetible de resumir_descartes.
        Qué hace: cuenta cuántas de las filas sin datos de UCI tienen número de instancia.
        Esperado: las dos filas principales con marcador ("Complete" e "Incomplete") no tienen instancia (0) y las
                  dos filas de imágenes repetibles, con marcador vacío, sí (2).
        """
        # Arrange: export sintético del fixture (las filas C y E son instancias repetibles de imágenes)

        # Act: resumir los descartes
        descartes = resumir_descartes(export_con_marcadores)

        # Assert: instancias por valor del marcador
        en_instancia = {d["marcador"]: d["en_instancia_repetible"] for d in descartes if d["instrumento"] == "uci"}
        assert en_instancia == {"Complete": 0, "Incomplete": 0, MARCADOR_VACIO: 2}

    def test_sin_columna_de_instancia_ninguna_fila_cuenta_como_repetible(self, export_con_marcadores):
        """
        Qué es: prueba unitaria de resumir_descartes sin la columna redcap_repeat_instance.
        Qué hace: elimina esa columna del export y resume los descartes.
        Esperado: no falla y en_instancia_repetible es 0 en todas las filas del resumen.
        """
        # Arrange: export sin la columna de instancia
        sin_instancia = export_con_marcadores.drop(columns=["redcap_repeat_instance"])

        # Act: resumir los descartes
        descartes = resumir_descartes(sin_instancia)

        # Assert: sin instancia no hay forma de saber si es repetible
        assert descartes and all(d["en_instancia_repetible"] == 0 for d in descartes)

    def test_no_modifica_el_dataframe_de_entrada(self, export_con_marcadores):
        """
        Qué es: prueba de que resumir_descartes no tiene efectos secundarios.
        Qué hace: compara el export antes y después de resumir los descartes.
        Esperado: el DataFrame queda idéntico.
        """
        # Arrange: copia de referencia
        antes = export_con_marcadores.copy()

        # Act: resumir los descartes
        resumir_descartes(export_con_marcadores)

        # Assert: sin cambios
        pd.testing.assert_frame_equal(export_con_marcadores, antes)

    def test_falla_si_falta_un_instrumento_esperado(self, export_con_marcadores):
        """
        Qué es: prueba de la validación de grupos dentro de resumir_descartes.
        Qué hace: elimina las columnas de UCI del export y resume los descartes.
        Esperado: ValueError que nombra el instrumento faltante (un cambio del diccionario de REDCap
                  detiene la corrida en lugar de propagarse).
        """
        # Arrange: export sin el instrumento uci
        sin_uci = export_con_marcadores.drop(columns=["dato_uci", "uci_complete"])

        # Act + Assert: se detiene con un mensaje explícito
        with pytest.raises(ValueError, match="uci"):
            resumir_descartes(sin_uci)
