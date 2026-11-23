"""
Pruebas de la huella por atención de la carga incremental (etl/load/warehouse/por_contrato.py).

Todas las tablas son sintéticas: llaves y valores inventados, sin ningún dato de pacientes ni base de datos.
"""
import numpy as np
import pandas as pd
import pytest

from etl.load.warehouse.contrato import CLAVE_ATENCION
from etl.load.warehouse.por_contrato import _canonico, _huellas


def _hecho(**valores) -> pd.DataFrame:
    """Dos atenciones con una medida y una clave de dimensión; `valores` sustituye lo de la primera."""
    base = {"iss": [9.5, 16.0], "desenlace_id": [1, 2]}
    base.update(valores)
    return pd.DataFrame({CLAVE_ATENCION: ["RC-1", "RC-2"], **base})


def _puente(filas: list[tuple]) -> pd.DataFrame:
    """Filas de un puente (llave, secuencia, imagen_id), sin fact_id."""
    return pd.DataFrame(filas, columns=[CLAVE_ATENCION, "secuencia", "imagen_id"])


PUENTE = [("RC-1", 1, 10), ("RC-1", 2, 11), ("RC-2", 1, 12)]


class TestHuellaDeLaAtencion:
    def test_misma_entrada_da_la_misma_huella_de_64_hexadecimales(self):
        """
        Qué es: prueba unitaria de _huellas (determinismo y forma).
        Qué hace: calcula la huella dos veces sobre las mismas tablas.
        Esperado: una huella por atención, de 64 caracteres hexadecimales en minúscula, idéntica en las dos corridas.
        """
        # Arrange: hecho y un puente
        puentes = [("bridge_atencion_imagen", _puente(PUENTE))]

        # Act
        primera, segunda = _huellas(_hecho(), puentes), _huellas(_hecho(), puentes)

        # Assert
        assert primera == segunda and set(primera) == {"RC-1", "RC-2"}
        assert all(len(h) == 64 and h == h.lower() and int(h, 16) >= 0 for h in primera.values())

    def test_el_orden_de_las_filas_del_puente_no_cambia_la_huella(self):
        """
        Qué es: prueba unitaria de la serialización canónica de los puentes.
        Qué hace: calcula la huella con las filas del puente en dos órdenes distintos.
        Esperado: la misma huella: el orden del staging no es un cambio.
        """
        # Arrange: las mismas filas, invertidas
        directo = [("bridge_atencion_imagen", _puente(PUENTE))]
        inverso = [("bridge_atencion_imagen", _puente(PUENTE[::-1]))]

        # Act + Assert
        assert _huellas(_hecho(), directo) == _huellas(_hecho(), inverso)

    def test_un_cambio_en_el_hecho_cambia_solo_la_huella_de_esa_atencion(self):
        """
        Qué es: prueba unitaria de la sensibilidad de la huella al hecho.
        Qué hace: cambia una medida de RC-1 y compara con la huella original.
        Esperado: cambia la huella de RC-1 y la de RC-2 queda igual.
        """
        # Arrange
        puentes = [("bridge_atencion_imagen", _puente(PUENTE))]

        # Act
        original = _huellas(_hecho(), puentes)
        cambiada = _huellas(_hecho(iss=[10.5, 16.0]), puentes)

        # Assert
        assert cambiada["RC-1"] != original["RC-1"]
        assert cambiada["RC-2"] == original["RC-2"]

    def test_un_cambio_solo_en_un_puente_cambia_la_huella(self):
        """
        Qué es: prueba unitaria de que la huella cubre los puentes (un cambio que no toca ninguna columna del hecho).
        Qué hace: cambia una imagen de RC-1 y agrega una fila del puente a RC-2, sin tocar el hecho.
        Esperado: cambian las huellas de RC-1 y de RC-2.
        """
        # Arrange
        original = _huellas(_hecho(), [("bridge_atencion_imagen", _puente(PUENTE))])

        # Act
        distinta = _huellas(_hecho(), [("bridge_atencion_imagen", _puente(
            [("RC-1", 1, 10), ("RC-1", 2, 99), ("RC-2", 1, 12), ("RC-2", 2, 13)]))])

        # Assert
        assert distinta["RC-1"] != original["RC-1"]
        assert distinta["RC-2"] != original["RC-2"]

    def test_un_cambio_de_columna_cambia_la_huella(self):
        """
        Qué es: prueba unitaria de que el nombre de la columna forma parte de la huella.
        Qué hace: calcula la huella con la misma medida bajo otro nombre de columna.
        Esperado: huellas distintas: un cambio del contrato fuerza a reescribir las atenciones.
        """
        # Arrange + Act
        con_iss = _huellas(_hecho(), [])
        con_otro_nombre = _huellas(_hecho().rename(columns={"iss": "iss_total"}), [])

        # Assert
        assert con_iss["RC-1"] != con_otro_nombre["RC-1"]


    def test_un_puente_con_una_atencion_ausente_del_hecho_falla(self):
        """
        Qué es: prueba unitaria de la validación de _huellas (puente huérfano).
        Qué hace: calcula la huella con un puente que trae una fila de una atención (RC-9) que no está en el hecho.
        Esperado: ValueError que nombra el puente y la atención; no se calcula una huella sobre datos inconsistentes.
        """
        # Arrange: el puente tiene una atención más que el hecho
        puentes = [("bridge_atencion_imagen", _puente(PUENTE + [("RC-9", 1, 14)]))]

        # Act + Assert
        with pytest.raises(ValueError, match="bridge_atencion_imagen.*RC-9"):
            _huellas(_hecho(), puentes)


class TestValorCanonico:
    @pytest.mark.parametrize("vacio", [None, np.nan, pd.NA, pd.NaT])
    def test_todos_los_vacios_son_none(self, vacio):
        """
        Qué es: prueba unitaria de _canonico con los vacíos de pandas (4 casos).
        Qué hace: normaliza None, NaN, NA y NaT.
        Esperado: None en todos: un vacío escrito de otra forma no es un cambio.
        """
        # Arrange: el vacío llega por parámetro

        # Act + Assert
        assert _canonico(vacio) is None

    def test_un_entero_que_llega_como_flotante_es_el_mismo_entero(self):
        """
        Qué es: prueba unitaria de _canonico con enteros y flotantes.
        Qué hace: normaliza 3, 3.0 y numpy.float64(3.0), y deja 3.5 como está.
        Esperado: los tres primeros dan 3: una columna con vacíos pasa a flotante y no debe parecer un cambio.
        """
        # Arrange: el mismo valor escrito de tres formas

        # Act + Assert
        assert _canonico(3) == _canonico(3.0) == _canonico(np.float64(3.0)) == 3
        assert _canonico(3.5) == 3.5

    def test_las_fechas_van_en_iso_y_los_booleanos_se_conservan(self):
        """
        Qué es: prueba unitaria de _canonico con fechas y booleanos.
        Qué hace: normaliza una fecha y hora, una fecha y los valores True y numpy.bool_.
        Esperado: texto ISO para las fechas; los booleanos no se convierten en 1 ni en 0.
        """
        # Arrange: valores sintéticos

        # Act + Assert
        assert _canonico(pd.Timestamp("2024-03-10 08:30")) == "2024-03-10T08:30:00"
        assert _canonico(pd.Timestamp("2024-03-10").date()) == "2024-03-10"
        assert _canonico(True) is True and _canonico(np.bool_(True)) is True
