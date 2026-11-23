"""
Pruebas de la regla de miembros por defecto de la ida y vuelta de las dimensiones (QR-EXA-04, etl/quality/origen.py).

Todos los valores son inventados (etiquetas como "etiqueta a"); no hay datos de pacientes ni base de datos.
"""
import pandas as pd

from etl.quality.origen import _con_miembros_por_defecto

TEXTO = {"caida", "superficie"}


class TestMiembrosPorDefectoDeLaIdaYVuelta:
    def test_un_atributo_de_texto_vacio_es_sin_dato(self):
        """
        Qué es: prueba unitaria de _con_miembros_por_defecto con un atributo vacío en una atención con datos.
        Qué hace: pasa una atención con la caída y la superficie vacía.
        Esperado: la superficie queda 'Sin dato' y la caída conserva su valor (el grupo no está vacío).
        """
        # Arrange: una atención con un atributo y otro vacío
        valores = pd.DataFrame({"caida": ["etiqueta a"], "superficie": [None]})

        # Act
        resultado = _con_miembros_por_defecto(valores, TEXTO, "no_aplica")

        # Assert
        assert resultado.iloc[0].tolist() == ["etiqueta a", "Sin dato"]

    def test_un_grupo_vacio_es_no_aplica_o_sin_dato_segun_el_contrato(self):
        """
        Qué es: prueba unitaria de _con_miembros_por_defecto con una atención sin ningún atributo.
        Qué hace: pasa una atención con todos los atributos vacíos con `vacio: no_aplica` y con `sin_dato`.
        Esperado: con `no_aplica`, todos los atributos de texto quedan 'No aplica'; con `sin_dato`, 'Sin dato'.
        """
        # Arrange: una atención vacía
        valores = pd.DataFrame({"caida": [None], "superficie": [None]})

        # Act
        no_aplica = _con_miembros_por_defecto(valores, TEXTO, "no_aplica")
        sin_dato = _con_miembros_por_defecto(valores, TEXTO, "sin_dato")

        # Assert
        assert no_aplica.iloc[0].tolist() == ["No aplica", "No aplica"]
        assert sin_dato.iloc[0].tolist() == ["Sin dato", "Sin dato"]

    def test_un_atributo_que_no_es_de_texto_queda_vacio_y_la_entrada_no_cambia(self):
        """
        Qué es: prueba unitaria de _con_miembros_por_defecto con un atributo numérico y la entrada original.
        Qué hace: pasa una atención con el orden (numérico) vacío y el texto con valor, y revisa la tabla de entrada.
        Esperado: el atributo numérico sigue vacío (no se le escribe ningún texto) y la tabla de entrada no se modifica.
        """
        # Arrange: el orden no es de texto
        valores = pd.DataFrame({"quinquenio": ["etiqueta a"], "orden": [None]})
        original = valores.copy()

        # Act
        resultado = _con_miembros_por_defecto(valores, {"quinquenio"}, "sin_dato")

        # Assert
        assert resultado.loc[0, "quinquenio"] == "etiqueta a" and pd.isna(resultado.loc[0, "orden"])
        pd.testing.assert_frame_equal(valores, original)
