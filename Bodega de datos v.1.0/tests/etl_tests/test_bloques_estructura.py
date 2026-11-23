import pandas as pd
import pytest

from etl.transform.redcap import bloques as modulo_bloques
from etl.transform.redcap.bloques import (
    INSTRUMENTOS_ESPERADOS,
    agrupar_por_instrumento,
    dividir_en_bloques,
    extraer_bloque,
    resumir_bloques,
    validar_dependencias,
    validar_grupos,
)

SISTEMA = ["record_id", "redcap_repeat_instrument", "redcap_repeat_instance"]


def _columnas_validas() -> list[str]:
    """Columnas de un export ficticio con los 15 instrumentos esperados: una de datos y su marcador cada uno."""
    columnas = list(SISTEMA)
    for nombre in INSTRUMENTOS_ESPERADOS:
        columnas += [f"dato_{nombre}", f"{nombre}_complete"]
    return columnas


class TestBloquesAgrupar:
    def test_agrupa_las_columnas_hasta_cada_marcador(self):
        """
        Qué es: prueba unitaria de agrupar_por_instrumento (caso normal).
        Qué hace: agrupa las columnas de un export ficticio de dos instrumentos con columnas de sistema.
        Esperado: cada instrumento contiene sus columnas de datos y su marcador; las columnas de sistema no
                  pertenecen a ningún grupo.
        """
        # Arrange: REDCap cierra cada instrumento con <instrumento>_complete
        columnas = [*SISTEMA, "a1", "a2", "uno_complete", "b1", "dos_complete"]

        # Act: agrupar
        grupos = agrupar_por_instrumento(columnas)

        # Assert: grupos delimitados por los marcadores, sin columnas de sistema
        assert grupos == {"uno": ["a1", "a2", "uno_complete"], "dos": ["b1", "dos_complete"]}

    def test_conserva_el_orden_de_las_columnas(self):
        """
        Qué es: prueba unitaria del orden de los grupos de agrupar_por_instrumento.
        Qué hace: agrupa tres instrumentos en un orden no alfabético.
        Esperado: los grupos salen en el orden en que aparecen sus marcadores en las columnas, sin reordenarse.
                  Este orden no decide el procesamiento: eso lo fija INSTRUMENTOS_ESPERADOS en dividir_en_bloques.
        """
        # Arrange: tres instrumentos en un orden no alfabético
        columnas = ["z1", "zeta_complete", "a1", "alfa_complete", "m1", "medio_complete"]

        # Act: agrupar
        grupos = agrupar_por_instrumento(columnas)

        # Assert: mismo orden que las columnas
        assert list(grupos) == ["zeta", "alfa", "medio"]

    def test_columnas_posteriores_al_ultimo_marcador_quedan_aparte(self):
        """
        Qué es: prueba unitaria de agrupar_por_instrumento con columnas sueltas al final.
        Qué hace: agrupa un export con columnas después del último marcador.
        Esperado: esas columnas forman el grupo "_sin_instrumento" (luego validar_grupos las rechaza).
        """
        # Arrange: una columna sin marcador de cierre
        columnas = ["a1", "uno_complete", "suelta"]

        # Act: agrupar
        grupos = agrupar_por_instrumento(columnas)

        # Assert: el grupo auxiliar recoge la sobrante
        assert grupos["_sin_instrumento"] == ["suelta"]


class TestBloquesValidarGrupos:
    def test_export_valido_no_falla(self):
        """
        Qué es: prueba unitaria de validar_grupos (caso normal).
        Qué hace: valida los grupos de un export ficticio con los 15 instrumentos esperados.
        Esperado: no lanza ninguna excepción.
        """
        # Arrange: columnas válidas y sus grupos
        columnas = _columnas_validas()
        grupos = agrupar_por_instrumento(columnas)

        # Act + Assert: no lanza
        validar_grupos(grupos, columnas)

    def test_columna_en_dos_grupos_falla(self):
        """
        Qué es: prueba unitaria de validar_grupos con una columna asignada dos veces.
        Qué hace: valida unos grupos donde una columna aparece en dos instrumentos.
        Esperado: ValueError que dice "más de un instrumento".
        """
        # Arrange: la columna "a1" en los dos grupos
        grupos = {"uno": ["a1", "uno_complete"], "dos": ["a1", "dos_complete"]}

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="más de un instrumento"):
            validar_grupos(grupos, ["a1", "uno_complete", "dos_complete"])

    def test_columna_sin_instrumento_falla(self):
        """
        Qué es: prueba unitaria de validar_grupos con una columna sin grupo.
        Qué hace: valida unos grupos que no incluyen una columna del export.
        Esperado: ValueError que nombra la columna sobrante.
        """
        # Arrange: "huerfana" está en el export pero en ningún grupo
        grupos = {"uno": ["a1", "uno_complete"]}

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="huerfana"):
            validar_grupos(grupos, ["a1", "uno_complete", "huerfana"])

    def test_instrumento_faltante_falla(self):
        """
        Qué es: prueba unitaria de la detección de cambios en el diccionario de REDCap (instrumento ausente).
        Qué hace: quita al export las columnas de UCI y valida.
        Esperado: ValueError que menciona el instrumento faltante.
        """
        # Arrange: export sin el instrumento uci
        columnas = [c for c in _columnas_validas() if "uci" not in c]

        # Act + Assert: se detiene en lugar de procesar un export incompleto
        with pytest.raises(ValueError, match=r"faltantes: \['uci'\]"):
            validar_grupos(agrupar_por_instrumento(columnas), columnas)

    def test_instrumento_inesperado_falla(self):
        """
        Qué es: prueba unitaria de la detección de cambios en el diccionario de REDCap (instrumento nuevo).
        Qué hace: agrega al export un instrumento que el transformer no conoce y valida.
        Esperado: ValueError que menciona el instrumento inesperado.
        """
        # Arrange: un instrumento nuevo en el proyecto REDCap
        columnas = [*_columnas_validas(), "dato_nuevo", "nuevo_complete"]

        # Act + Assert: se detiene en lugar de ignorar sus datos
        with pytest.raises(ValueError, match=r"inesperados: \['nuevo'\]"):
            validar_grupos(agrupar_por_instrumento(columnas), columnas)


class TestBloquesDependencias:
    def test_el_orden_actual_respeta_las_dependencias(self):
        """
        Qué es: prueba unitaria de validar_dependencias con la configuración real.
        Qué hace: valida DEPENDENCIAS contra INSTRUMENTOS_ESPERADOS.
        Esperado: no lanza (cada instrumento se procesa después de aquellos de los que depende).
        """
        # Arrange: configuración real del módulo

        # Act + Assert: no lanza
        validar_dependencias()

    def test_dependencia_procesada_despues_falla(self, monkeypatch):
        """
        Qué es: prueba unitaria de validar_dependencias con un orden incorrecto.
        Qué hace: declara que la demografía depende de UCI, que se procesa al final.
        Esperado: ValueError que dice que depende de un instrumento que se procesa después.
        """
        # Arrange: dependencia imposible de cumplir con el orden de procesamiento
        monkeypatch.setattr(modulo_bloques, "DEPENDENCIAS", {"informacion_demografica": ("uci",)})

        # Act + Assert: se detiene antes de transformar
        with pytest.raises(ValueError, match="depende de 'uci'"):
            validar_dependencias()


class TestBloquesExtraerBloque:
    def test_conserva_la_clave_y_los_datos_y_excluye_marcador_e_identificadores(self):
        """
        Qué es: prueba unitaria de extraer_bloque (columnas).
        Qué hace: extrae un bloque con identificadores directos, un dato y el marcador.
        Esperado: quedan las tres columnas de la clave y el dato; el marcador, el nombre y la fecha de
                  nacimiento (EXCLUIR_DEL_DW) no pasan al bloque.
        """
        # Arrange: fila ficticia del instrumento demográfico
        df = pd.DataFrame({
            "record_id": ["1"], "redcap_repeat_instrument": [None], "redcap_repeat_instance": [None],
            "nombre": ["Persona Uno"], "fecha_de_nacimiento": ["1990-05-01"], "genero": ["M"],
            "informacion_demografica_complete": ["Complete"],
        })
        columnas = ["nombre", "fecha_de_nacimiento", "genero", "informacion_demografica_complete"]

        # Act: extraer
        bloque = extraer_bloque(df, columnas)

        # Assert: solo clave y dato clínico
        assert list(bloque.columns) == [*SISTEMA, "genero"]

    def test_descarta_filas_sin_datos_y_conserva_las_parciales(self):
        """
        Qué es: prueba unitaria del criterio "fila con dato" (decisión 2.6).
        Qué hace: extrae un bloque de tres filas: sin ningún dato, con solo el primero y con solo el segundo.
        Esperado: se descarta la fila vacía y se conservan las dos parciales; el índice queda consecutivo.
        """
        # Arrange: tres filas con distinta completitud
        df = pd.DataFrame({
            "record_id": ["1", "2", "3"], "a": [None, "x", None], "b": [None, None, "y"],
            "uno_complete": ["Complete", None, None],
        })

        # Act: extraer
        bloque = extraer_bloque(df, ["a", "b", "uno_complete"])

        # Assert: how="all" y no how="any"
        assert bloque["record_id"].tolist() == ["2", "3"]
        assert bloque.index.tolist() == [0, 1]

    def test_no_modifica_el_dataframe_de_entrada(self):
        """
        Qué es: prueba unitaria de efectos secundarios de extraer_bloque.
        Qué hace: extrae un bloque y compara el DataFrame original con una copia.
        Esperado: el DataFrame original queda idéntico.
        """
        # Arrange: copia de referencia
        df = pd.DataFrame({"record_id": ["1", "2"], "a": [None, "x"], "uno_complete": [None, None]})
        copia = df.copy()

        # Act: extraer
        extraer_bloque(df, ["a", "uno_complete"])

        # Assert: sin cambios
        pd.testing.assert_frame_equal(df, copia)

    def test_dividir_devuelve_un_bloque_por_instrumento_en_el_orden_esperado(self):
        """
        Qué es: prueba unitaria de dividir_en_bloques (estructura de la salida).
        Qué hace: divide un export ficticio con los 15 instrumentos.
        Esperado: un bloque por instrumento, en el orden de INSTRUMENTOS_ESPERADOS.
        """
        # Arrange: un export vacío con las columnas válidas
        df = pd.DataFrame(columns=_columnas_validas())

        # Act: dividir
        bloques = dividir_en_bloques(df)

        # Assert: mismas claves y mismo orden
        assert list(bloques) == list(INSTRUMENTOS_ESPERADOS)


class TestBloquesResumir:
    def test_distingue_instrumento_repetible_de_no_repetible(self):
        """
        Qué es: prueba unitaria de resumir_bloques (conteos).
        Qué hace: resume un bloque repetible (dos filas para un episodio) y otro no repetible.
        Esperado: el repetible tiene 3 filas, 2 episodios, máximo 2 filas por episodio y repetible = True; el no
                  repetible, 1 fila por episodio, repetible = False y sin columnas en conflicto.
        """
        # Arrange: instancias numeradas solo en el repetible
        bloques = {
            "imagenes": pd.DataFrame({"record_id": ["1", "1", "2"], "redcap_repeat_instance": [1, 2, 1],
                                      "dato": ["a", "b", "c"]}),
            "uno": pd.DataFrame({"record_id": ["1", "2"], "redcap_repeat_instance": [None, None],
                                 "dato": ["a", "b"]}),
        }

        # Act: resumir
        resumen = {fila["instrumento"]: fila for fila in resumir_bloques(bloques)}

        # Assert: conteos por instrumento
        imagenes = resumen["imagenes"]
        assert (imagenes["n_filas"], imagenes["n_record_id"], imagenes["max_filas_por_record"]) == (3, 2, 2)
        assert imagenes["repetible"] is True and imagenes["n_columnas_datos"] == 1
        uno = resumen["uno"]
        assert (uno["n_filas"], uno["max_filas_por_record"], uno["repetible"]) == (2, 1, False)
        assert uno["columnas_en_conflicto"] == 0

    @pytest.mark.parametrize("valores, conflictos", [(["a", "b"], 1), (["a", "a"], 0)])
    def test_instrumento_no_repetible_con_dos_filas_por_episodio(self, valores, conflictos):
        """
        Qué es: prueba unitaria de columnas_en_conflicto dentro de resumir_bloques.
        Qué hace: resume un instrumento no repetible con dos filas del mismo episodio, con valores distintos y
                  con valores iguales (2 casos).
        Esperado: 1 columna en conflicto cuando los valores difieren y 0 cuando coinciden: solo lo primero exige revisión.
        """
        # Arrange: el episodio "1" aparece dos veces sin instancia
        bloques = {"uno": pd.DataFrame({"record_id": ["1", "1"], "redcap_repeat_instance": [None, None],
                                        "dato": valores})}

        # Act: resumir
        fila = resumir_bloques(bloques)[0]

        # Assert: hay más de una fila por episodio y el conflicto depende de los valores
        assert fila["max_filas_por_record"] == 2 and fila["repetible"] is False
        assert fila["columnas_en_conflicto"] == conflictos

    def test_bloque_vacio_resume_en_ceros(self):
        """
        Qué es: prueba unitaria de resumir_bloques con un bloque sin filas.
        Qué hace: resume un bloque vacío (ningún episodio con datos del instrumento).
        Esperado: 0 filas, 0 episodios, máximo 0, no repetible y sin conflictos (no falla al calcular máximos).
        """
        # Arrange: bloque con columnas pero sin filas
        bloques = {"uno": pd.DataFrame(columns=["record_id", "redcap_repeat_instance", "dato"])}

        # Act: resumir
        fila = resumir_bloques(bloques)[0]

        # Assert: todo en cero
        assert (fila["n_filas"], fila["n_record_id"], fila["max_filas_por_record"]) == (0, 0, 0)
        assert fila["repetible"] is False and fila["columnas_en_conflicto"] == 0
