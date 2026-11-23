import pandas as pd
import pytest

from etl.transform.redcap.consolidacion import fecha_de_particion, leer_particiones

DEST = "registro_trauma_redcap"


def _escribir(raiz, particion, df, archivo=f"{DEST}.parquet"):
    """Escribe df en <raiz>/load_date=<particion>/<archivo>."""
    carpeta = raiz / f"load_date={particion}"
    carpeta.mkdir(parents=True)
    df.to_parquet(carpeta / archivo, index=False)


class TestLeerParticiones:
    def test_lee_cada_particion_ordenada_por_nombre(self, tmp_path):
        """
        Qué es: prueba unitaria de leer_particiones con particiones en disco.
        Qué hace: escribe dos particiones sintéticas (en desorden) y las lee.
        Esperado: devuelve un diccionario con los nombres sin el prefijo "load_date=", en orden cronológico,
                  y con DataFrames idénticos a los escritos.
        """
        # Arrange: la partición más nueva se escribe primero para comprobar que el orden no depende del disco
        nueva = pd.DataFrame({"record_id": ["1", "2"], "x": ["a", "b"]})
        antigua = pd.DataFrame({"record_id": ["1"], "x": ["c"]})
        _escribir(tmp_path, "2026-10-02T100000", nueva)
        _escribir(tmp_path, "2026-10-01T100000", antigua)

        # Act: leer
        particiones = leer_particiones(tmp_path, DEST)

        # Assert: nombres ordenados y contenido intacto
        assert list(particiones) == ["2026-10-01T100000", "2026-10-02T100000"]
        pd.testing.assert_frame_equal(particiones["2026-10-01T100000"], antigua)
        pd.testing.assert_frame_equal(particiones["2026-10-02T100000"], nueva)

    def test_ignora_carpetas_sin_el_archivo_y_archivos_de_otro_dataset(self, tmp_path):
        """
        Qué es: prueba unitaria de los filtros de leer_particiones.
        Qué hace: crea una partición válida, otra sin el archivo del dataset, una con un archivo de otro
                  dataset y una carpeta que no es una partición.
        Esperado: solo se lee la partición válida.
        """
        # Arrange: una válida y tres distractores
        df = pd.DataFrame({"record_id": ["1"]})
        _escribir(tmp_path, "2026-10-01T100000", df)
        (tmp_path / "load_date=2026-10-02T100000").mkdir()
        _escribir(tmp_path, "2026-10-03T100000", df, archivo="otro_dataset.parquet")
        (tmp_path / "otra_carpeta").mkdir()

        # Act: leer
        particiones = leer_particiones(tmp_path, DEST)

        # Assert: solo la partición con el archivo esperado
        assert list(particiones) == ["2026-10-01T100000"]

    def test_sin_particiones_devuelve_diccionario_vacio(self, tmp_path):
        """
        Qué es: prueba unitaria de leer_particiones sobre una raw vacía.
        Qué hace: lee un directorio sin particiones.
        Esperado: diccionario vacío (es consolidar_particiones quien decide fallar).
        """
        # Arrange: directorio temporal vacío

        # Act: leer
        particiones = leer_particiones(tmp_path, DEST)

        # Assert: sin particiones
        assert particiones == {}


class TestFechaDeParticion:
    def test_interpreta_el_nombre_de_la_particion(self):
        """
        Qué es: prueba unitaria de fecha_de_particion (nombre válido).
        Qué hace: interpreta un nombre con el formato de raw (%Y-%m-%dT%H%M%S).
        Esperado: el Timestamp correspondiente, con hora, minuto y segundo.
        """
        # Arrange: nombre de partición sintético
        nombre = "2026-10-08T173005"

        # Act: interpretar
        fecha = fecha_de_particion(nombre)

        # Assert: la fecha completa
        assert fecha == pd.Timestamp("2026-10-08 17:30:05")

    @pytest.mark.parametrize("nombre", ["2026-10-08", "partición", "2026-13-45T000000"])
    def test_nombre_con_otro_formato_devuelve_none(self, nombre):
        """
        Qué es: prueba unitaria de fecha_de_particion (nombre no reconocido).
        Qué hace: interpreta una fecha sin hora, un texto cualquiera y una fecha imposible (3 casos).
        Esperado: None en los tres casos: la fecha de extracción queda sin definir en lugar de inventarse.
        """
        # Arrange: nombre parametrizado

        # Act: interpretar
        fecha = fecha_de_particion(nombre)

        # Assert: no reconocido
        assert fecha is None
