import pandas as pd
import pytest

from etl.transform.common.cleaning import (
    aplicar_renombres,
    eliminar_columnas,
    normalizar_columnas,
    normalizar_nombre,
    renombrar_columnas,
    vacios_a_nulo,
)


@pytest.fixture
def escribir_yaml(tmp_path):
    """
    Devuelve una función que escribe un YAML de renombres sintético en un directorio temporal
    aislado de pytest (nunca toca config/renombres_columnas_redcap.yaml) y retorna su ruta.
    """
    def _escribir(contenido: str):
        ruta = tmp_path / "renombres.yaml"
        ruta.write_text(contenido, encoding="utf-8")
        return ruta
    return _escribir


class TestNormalizacionDeNombres:
    @pytest.mark.parametrize("original, esperado", [
        ("Fecha y Hora de Llegada", "fecha_y_hora_de_llegada"),
        ("Número de Identificación (CC)", "numero_de_identificacion_cc"),
        ("  Edad__en años ", "edad_en_anos"),
    ])
    def test_normalizar_nombre(self, original, esperado):
        """
        Qué es: prueba unitaria de normalizar_nombre.
        Qué hace: normaliza nombres con mayúsculas, tildes, paréntesis y espacios o guiones repetidos.
        Esperado: minúsculas, sin tildes y con "_" como único separador, sin "_" en los extremos.
        """
        # Arrange: el nombre original llega como parámetro

        # Act: normalizar
        resultado = normalizar_nombre(original)

        # Assert: nombres estables para el mapeo columna -> dimensión
        assert resultado == esperado

    def test_columnas_de_sistema_no_se_normalizan_y_se_devuelve_equivalencia(self):
        """
        Qué es: prueba unitaria de normalizar_columnas.
        Qué hace: normaliza un DataFrame sintético con una columna de sistema de REDCap y una normal.
        Esperado: "record_id" queda intacta, "Edad (años)" pasa a "edad_anos", la equivalencia lo
                  registra y los datos no cambian.
        """
        # Arrange: una columna de sistema y una columna con tilde y paréntesis
        df = pd.DataFrame({"record_id": ["1"], "Edad (años)": [30]})

        # Act: normalizar
        nuevo, equivalencia = normalizar_columnas(df)

        # Assert: nombres nuevos, trazabilidad original -> final y datos intactos
        assert list(nuevo.columns) == ["record_id", "edad_anos"]
        assert equivalencia == {"record_id": "record_id", "Edad (años)": "edad_anos"}
        assert nuevo["edad_anos"].tolist() == [30]

    def test_colision_de_nombres_lanza_valueerror(self):
        """
        Qué es: prueba unitaria de validación de normalizar_columnas.
        Qué hace: normaliza un DataFrame con dos columnas que colapsan al mismo nombre ("Edad" y "edad").
        Esperado: lanza ValueError; no se pueden fusionar columnas distintas en silencio.
        """
        # Arrange: dos columnas distintas que normalizan igual
        df = pd.DataFrame([[1, 2]], columns=["Edad", "edad"])

        # Act + Assert: debe detenerse antes de perder una de las dos columnas
        with pytest.raises(ValueError):
            normalizar_columnas(df)


class TestVaciosANulo:
    def test_vacios_y_espacios_pasan_a_nulo_real(self):
        """
        Qué es: prueba unitaria de vacios_a_nulo.
        Qué hace: convierte una columna con valor, cadena vacía, solo espacios y nulo real.
        Esperado: las tres últimas quedan como nulo y el valor con contenido se conserva.
        """
        # Arrange: el modo "label" de REDCap exporta los vacíos como texto
        df = pd.DataFrame({"a": ["x", "", "   ", None]})

        # Act: convertir
        resultado = vacios_a_nulo(df)

        # Assert: sin esto dropna/duplicated/nunique inflarían duplicados y subestimarían nulos
        assert resultado["a"].isna().tolist() == [False, True, True, True]
        assert resultado["a"].iloc[0] == "x"


class TestAplicarRenombresYaml:
    def test_renombra_y_conserva_la_trazabilidad(self, escribir_yaml):
        """
        Qué es: prueba unitaria de aplicar_renombres (caso normal).
        Qué hace: aplica un YAML sintético que corrige "direcci_n" a "direccion".
        Esperado: la columna se renombra y la equivalencia original -> final apunta al nombre corregido,
                  sin tocar las demás.
        """
        # Arrange: columna deformada por REDCap y su equivalencia desde el nombre original
        ruta = escribir_yaml("direcci_n: direccion\n")
        df = pd.DataFrame({"record_id": ["1"], "direcci_n": ["x"], "edad": [1]})
        equivalencia = {"record_id": "record_id", "Dirección": "direcci_n", "edad": "edad"}

        # Act: aplicar los renombres
        nuevo, equivalencia_final = aplicar_renombres(df, equivalencia, ruta)

        # Assert: la capa semántica corrige el nombre y deja la trazabilidad completa
        assert list(nuevo.columns) == ["record_id", "direccion", "edad"]
        assert equivalencia_final == {"record_id": "record_id", "Dirección": "direccion", "edad": "edad"}

    def test_columna_inexistente_lanza_keyerror(self, escribir_yaml):
        """
        Qué es: prueba unitaria de validación de aplicar_renombres.
        Qué hace: aplica un YAML que renombra una columna que el DataFrame no tiene.
        Esperado: lanza KeyError (el origen cambió y el pipeline debe detenerse).
        """
        # Arrange: el YAML menciona una columna ausente
        ruta = escribir_yaml("no_existe: otra\n")
        df = pd.DataFrame({"record_id": ["1"]})

        # Act + Assert: un cambio en el origen no debe pasar en silencio
        with pytest.raises(KeyError):
            aplicar_renombres(df, {"record_id": "record_id"}, ruta)

    def test_destino_existente_lanza_valueerror(self, escribir_yaml):
        """
        Qué es: prueba unitaria de validación de aplicar_renombres.
        Qué hace: aplica un YAML cuyo nombre destino ya existe como otra columna.
        Esperado: lanza ValueError (el renombre pisaría una columna).
        """
        # Arrange: "direcci_n" -> "edad", pero "edad" ya existe
        ruta = escribir_yaml("direcci_n: edad\n")
        df = pd.DataFrame({"direcci_n": ["x"], "edad": [1]})

        # Act + Assert: no se permite colisionar con una columna existente
        with pytest.raises(ValueError):
            aplicar_renombres(df, {"direcci_n": "direcci_n", "edad": "edad"}, ruta)

    def test_yaml_vacio_no_cambia_nada(self, escribir_yaml):
        """
        Qué es: prueba unitaria de aplicar_renombres (YAML sin entradas).
        Qué hace: aplica un archivo YAML vacío.
        Esperado: el DataFrame y la equivalencia quedan sin cambios.
        """
        # Arrange: archivo vacío (yaml.safe_load devuelve None)
        ruta = escribir_yaml("")
        df = pd.DataFrame({"record_id": ["1"]})
        equivalencia = {"record_id": "record_id"}

        # Act: aplicar
        nuevo, equivalencia_final = aplicar_renombres(df, equivalencia, ruta)

        # Assert: sin renombres declarados no hay cambios
        assert list(nuevo.columns) == ["record_id"]
        assert equivalencia_final == equivalencia


class TestRenombrarColumnasPorBloque:
    def test_renombra_y_registra_en_el_reporte(self, reporte):
        """
        Qué es: prueba unitaria de renombrar_columnas.
        Qué hace: renombra "descripcion" a "descripcion_imagen" en el bloque "imagenes".
        Esperado: la columna cambia de nombre y el reporte guarda original, nuevo y motivo.
        """
        # Arrange: un bloque sintético con la columna a alinear con el modelo
        df = pd.DataFrame({"descripcion": ["x"]})

        # Act: renombrar
        nuevo = renombrar_columnas(df, reporte, "imagenes", {"descripcion": "descripcion_imagen"},
                                   "alinear con DIM_IMAGEN")

        # Assert: el renombre queda trazable (nombres, sin datos)
        assert list(nuevo.columns) == ["descripcion_imagen"]
        assert reporte.renombres[("imagenes", "descripcion")]["columna_nueva"] == "descripcion_imagen"

    def test_origen_inexistente_lanza_keyerror(self, reporte):
        """
        Qué es: prueba unitaria de validación de renombrar_columnas.
        Qué hace: renombra una columna que el bloque no tiene.
        Esperado: lanza KeyError y no registra nada en el reporte.
        """
        # Arrange: bloque sin la columna pedida
        df = pd.DataFrame({"a": [1]})

        # Act + Assert: falla de forma explícita y sin dejar un registro falso
        with pytest.raises(KeyError):
            renombrar_columnas(df, reporte, "demo", {"no_existe": "otra"}, "prueba")
        assert reporte.renombres == {}

    def test_destino_existente_lanza_valueerror(self, reporte):
        """
        Qué es: prueba unitaria de validación de renombrar_columnas.
        Qué hace: renombra una columna a un nombre que otra columna ya usa.
        Esperado: lanza ValueError.
        """
        # Arrange: "a" -> "b", pero "b" ya existe
        df = pd.DataFrame({"a": [1], "b": [2]})

        # Act + Assert: no se permite pisar una columna existente
        with pytest.raises(ValueError):
            renombrar_columnas(df, reporte, "demo", {"a": "b"}, "prueba")


class TestEliminarColumnas:
    def test_elimina_y_registra_conteo_y_motivo(self, reporte):
        """
        Qué es: prueba unitaria de eliminar_columnas (common/cleaning.py).
        Qué hace: elimina dos columnas sintéticas de un bloque: una con 2 valores informados y otra vacía.
        Esperado: las columnas desaparecen y `exclusiones` guarda, por columna, solo el conteo de filas con valor y el
                  motivo (nunca los valores).
        """
        # Arrange
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", None, "y"], "c": [None, None, None]})

        # Act
        nuevo = eliminar_columnas(df, reporte, "demo", ["b", "c"], "sin uso en ningun modelo")

        # Assert
        assert list(nuevo.columns) == ["a"]
        tabla = reporte.tabla("exclusiones").set_index("columna")
        assert tabla.loc["b", "filas_con_valor"] == 2 and tabla.loc["c", "filas_con_valor"] == 0
        assert set(tabla["motivo"]) == {"sin uso en ningun modelo"}

    def test_columna_inexistente_lanza_keyerror_sin_registrar(self, reporte):
        """
        Qué es: prueba unitaria de validación de eliminar_columnas.
        Qué hace: elimina una columna que el bloque no tiene.
        Esperado: KeyError y ninguna exclusión registrada (un cambio del origen no pasa inadvertido).
        """
        # Arrange
        df = pd.DataFrame({"a": [1]})

        # Act + Assert
        with pytest.raises(KeyError):
            eliminar_columnas(df, reporte, "demo", ["no_existe"], "prueba")
        assert reporte.exclusiones == {}

    def test_excluir_dos_veces_la_misma_columna_lanza_valueerror(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.registrar_exclusion.
        Qué hace: registra dos veces la exclusión de la misma columna del mismo bloque.
        Esperado: ValueError (es un error de lógica del transformer).
        """
        # Arrange
        reporte.registrar_exclusion("demo", "a", 1, "prueba")

        # Act + Assert
        with pytest.raises(ValueError, match="ya fue excluida"):
            reporte.registrar_exclusion("demo", "a", 1, "prueba")
