"""
Pruebas de la lectura de las listas de valores permitidos (`etl/quality/dominios.py`, QR-DOM-04).

Todo es sintético: archivos YAML escritos en una carpeta temporal con valores inventados y el contrato real del modelo
completo (solo nombres de dimensiones y atributos, sin datos). No hay conexión a la base.
"""
from pathlib import Path

import pytest

from config.settings import CONTRATOS_DIR
from etl.load.warehouse.contrato import leer_contrato
from etl.quality.dominios import ValoresPermitidosInvalidos, leer_permitidos


@pytest.fixture(scope="module")
def contrato():
    """El contrato del modelo completo: solo esquema (dimensiones y atributos), sin datos."""
    return leer_contrato(str(Path(CONTRATOS_DIR) / "completo.yaml"), "completo")


def _archivo(tmp_path, contenido: str) -> Path:
    ruta = tmp_path / "valores_permitidos.yaml"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


class TestLeerPermitidos:
    def test_lee_las_listas_por_dimension_y_atributo(self, tmp_path, contrato):
        """
        Qué es: prueba unitaria de `leer_permitidos`, caso válido.
        Qué hace: lee un archivo con dos atributos de dos dimensiones del contrato, con valores inventados.
        Esperado: devuelve {dimensión: {atributo: [valores]}} con los mismos valores y en el mismo orden.
        """
        # Arrange
        ruta = _archivo(tmp_path, 'dim_paciente:\n  genero: ["Valor A", "Valor B"]\ndim_desenlace:\n  autopsia: ["Si", "No"]\n')

        # Act
        permitidos = leer_permitidos(ruta, contrato)

        # Assert
        assert permitidos == {"dim_paciente": {"genero": ["Valor A", "Valor B"]},
                              "dim_desenlace": {"autopsia": ["Si", "No"]}}

    def test_un_archivo_vacio_no_define_listas(self, tmp_path, contrato):
        """
        Qué es: prueba unitaria de `leer_permitidos`, archivo sin contenido (la plantilla sin llenar).
        Qué hace: lee un archivo vacío.
        Esperado: devuelve un mapa vacío: QR-DOM-04 no evalúa ningún atributo.
        """
        # Arrange
        ruta = _archivo(tmp_path, "")

        # Act + Assert
        assert leer_permitidos(ruta, contrato) == {}

    def test_rechaza_dimensiones_y_atributos_que_no_existen_con_todos_los_problemas(self, tmp_path, contrato):
        """
        Qué es: prueba unitaria de la validación de nombres contra el contrato.
        Qué hace: lee un archivo con una dimensión inexistente, un catálogo (que no es dimensión) y un atributo
                  inexistente de una dimensión real.
        Esperado: lanza ValoresPermitidosInvalidos con los tres problemas en el mismo mensaje (un error de digitación
                  no debe dejar la regla sin evaluar en silencio).
        """
        # Arrange
        ruta = _archivo(tmp_path, 'dim_inventada:\n  x: ["a"]\ndim_cie_10:\n  x: ["a"]\ndim_paciente:\n  atributo_inventado: ["a"]\n')

        # Act
        with pytest.raises(ValoresPermitidosInvalidos) as error:
            leer_permitidos(ruta, contrato)

        # Assert
        mensaje = str(error.value)
        assert "dim_inventada" in mensaje and "dim_cie_10" in mensaje and "dim_paciente.atributo_inventado" in mensaje

    def test_rechaza_valores_que_yaml_no_lee_como_texto(self, tmp_path, contrato):
        """
        Qué es: prueba unitaria de la validación de tipos de los valores.
        Qué hace: lee una lista con `No` y `10` sin comillas, que YAML interpreta como booleano y número.
        Esperado: lanza ValoresPermitidosInvalidos y el mensaje pide poner los valores entre comillas; si pasara, la
                  lista cambiaría de significado sin avisar.
        """
        # Arrange
        ruta = _archivo(tmp_path, "dim_desenlace:\n  autopsia: [Si, No, 10]\n")

        # Act
        with pytest.raises(ValoresPermitidosInvalidos) as error:
            leer_permitidos(ruta, contrato)

        # Assert
        assert "dim_desenlace.autopsia" in str(error.value) and "comillas" in str(error.value)

    def test_rechaza_listas_vacias_y_estructuras_que_no_son_mapas(self, tmp_path, contrato):
        """
        Qué es: prueba unitaria de la validación de la estructura.
        Qué hace: lee una lista vacía para un atributo, una dimensión sin mapa de atributos y un archivo que es una lista.
        Esperado: los tres casos lanzan ValoresPermitidosInvalidos: una lista vacía marcaría todo valor como fuera de dominio.
        """
        # Arrange
        vacia = _archivo(tmp_path, "dim_paciente:\n  genero: []\n")
        sin_mapa = tmp_path / "otra.yaml"
        sin_mapa.write_text("dim_paciente: [a, b]\n", encoding="utf-8")
        lista = tmp_path / "lista.yaml"
        lista.write_text("- a\n- b\n", encoding="utf-8")

        # Act + Assert
        for ruta in (vacia, sin_mapa, lista):
            with pytest.raises(ValoresPermitidosInvalidos):
                leer_permitidos(ruta, contrato)
