import pandas as pd
import pytest

from etl.transform.common.cie10 import (
    buscar_candidatos,
    candidatos_sin_pareja,
    cargar_catalogo,
    cargar_universo,
    indice_por_texto,
    mapear_texto_a_cie10,
    redacciones_alternas,
    unificar_etiquetas_canonicas,
)
from etl.transform.redcap.instrumentos import cie_10_diagnosticos, comorbilidades, complicaciones

BLOQUE = "codigos_cie10"
LINEAS = [
    "R31 HEMATURIA NO ESPECIFICADA",          # redacción alterna de R31
    "R31 HEMATURIA, NO ESPECIFICADA",         # canónica de R31
    "I46 PARO CARDIACO",
    "F001* DEMENCIA EN LA ENFERMEDAD DE ALZHEIMER DE COMIENZO TARDIO",
    "F001 DEMENCIA EN LA ENFERMEDAD DE ALZHEIMER DE COMIENZO TARDIO",
    "G01* MENINGITIS EN ENFERMEDADES BACTERIANAS CLASIFICADAS EN OTRA PARTE",   # solo existe con símbolo
    "E876 HIPOPOTASEMIA",
]
CANONICAS = 'etiquetas_canonicas:\n  R31: "R31 HEMATURIA, NO ESPECIFICADA"\n'


@pytest.fixture
def rutas(tmp_path):
    """
    Catálogo CIE-10 sintético y mínimo (7 líneas con el formato de las opciones de REDCap: una pareja con dos
    redacciones, una pareja con y sin símbolo y un código que solo existe con símbolo) y su YAML de etiquetas
    canónicas, en una carpeta temporal. Aislado del catálogo real y sin datos de pacientes.
    """
    catalogo = tmp_path / "cie10.csv"
    pd.DataFrame({"codigo_cie10": LINEAS}).to_csv(catalogo, index=False, encoding="utf-8")
    canonicas = tmp_path / "canonicas.yaml"
    canonicas.write_text(CANONICAS, encoding="utf-8")
    return catalogo, canonicas


@pytest.fixture
def catalogo(rutas):
    """Catálogo sintético cargado (con la etiqueta canónica aplicada)."""
    return cargar_catalogo(*rutas)


AJUSTES = {"correcciones_texto": {"Hipopotasmia": "Hipopotasemia"},
           "equivalencias": {"Paro del corazon": "I46 PARO CARDIACO"}}


class TestCatalogoCie10:
    def test_quita_la_redaccion_alterna_y_conserva_los_simbolos(self, catalogo):
        """
        Qué es: prueba unitaria de cargar_catalogo (parejas con y sin símbolo y etiqueta canónica).
        Qué hace: carga el catálogo sintético.
        Esperado: R31 queda una sola vez con la etiqueta canónica; F001 y F001* quedan como dos miembros con la misma
                  clave; las líneas conservan su * tal cual.
        """
        # Arrange: catálogo de la fixture

        # Act: consultar miembros
        lineas = set(catalogo["linea"])

        # Assert
        assert "R31 HEMATURIA NO ESPECIFICADA" not in lineas and "R31 HEMATURIA, NO ESPECIFICADA" in lineas
        assert len(catalogo) == len(LINEAS) - 1
        assert set(catalogo.loc[catalogo["clave"] == "F001", "codigo"]) == {"F001", "F001*"}

    def test_canonica_inexistente_falla(self, rutas, tmp_path):
        """
        Qué es: prueba unitaria de la validación del catálogo.
        Qué hace: carga un YAML de canónicas con una línea que no está en el catálogo.
        Esperado: ValueError, para no introducir una etiqueta que REDCap no ofrece.
        """
        # Arrange
        malo = tmp_path / "malo.yaml"
        malo.write_text('etiquetas_canonicas:\n  R31: "R31 HEMATURIA (INVENTADA)"\n', encoding="utf-8")

        # Act + Assert
        with pytest.raises(ValueError, match="no están en el catálogo"):
            cargar_catalogo(rutas[0], malo)

    def test_indice_prefiere_la_version_sin_simbolo(self, catalogo):
        """
        Qué es: prueba unitaria de indice_por_texto (decisión 7.1).
        Qué hace: busca la etiqueta de F001, que existe con y sin asterisco, y la de G01, que solo existe con él.
        Esperado: F001 apunta a la línea sin símbolo; G01 conserva su asterisco.
        """
        # Arrange + Act
        indice = indice_por_texto(catalogo)

        # Assert
        assert indice["demencia en la enfermedad de alzheimer de comienzo tardio"].startswith("F001 ")
        assert indice["meningitis en enfermedades bacterianas clasificadas en otra parte"].startswith("G01* ")

    def test_catalogo_real_carga_sin_ambiguedad(self):
        """
        Qué es: prueba de integridad del catálogo real (config/catalogos/cie10_redcap.csv, solo opciones de REDCap).
        Qué hace: carga el catálogo con sus etiquetas canónicas.
        Esperado: 2 190 miembros (2 196 líneas menos las 6 redacciones alternas) y ninguna etiqueta ambigua.
        """
        # Arrange: rutas por defecto

        # Act
        cat = cargar_catalogo()

        # Assert
        assert len(cat) == 2190
        assert len(redacciones_alternas()) == 6


class TestMapearTextoACie10:
    def test_mapea_conserva_sin_pareja_y_audita(self, catalogo, reporte, regla):
        """
        Qué es: prueba unitaria de mapear_texto_a_cie10 (Excel).
        Qué hace: mapea seis textos sintéticos: uno exacto con tildes y minúsculas, uno con dos símbolos posibles, uno
                  por equivalencia revisada, uno con error ortográfico, uno sin pareja y un vacío.
        Esperado: los cuatro primeros pasan a la línea de REDCap (R31 canónica, F001 sin símbolo, I46 e E876); el
                  sin pareja conserva su texto en MAYÚSCULAS con marca False; el vacío queda vacío; la regla cuenta 1 de 5 sin pareja
                  y la auditoría conserva.
        """
        # Arrange
        df = pd.DataFrame({"cie10": ["Hematuria, no especificada",
                                     "Demencia en la enfermedad de Alzheimer de comienzo tardío",
                                     "Paro del corazón", "Hipopotasmia", "Fiebre persistente", None]})

        # Act
        mapear_texto_a_cie10(df, reporte, BLOQUE, "cie10", "cie10_mapeado", catalogo, AJUSTES)

        # Assert: valores y marca
        assert df["cie10"].tolist()[:5] == [
            "R31 HEMATURIA, NO ESPECIFICADA", "F001 DEMENCIA EN LA ENFERMEDAD DE ALZHEIMER DE COMIENZO TARDIO",
            "I46 PARO CARDIACO", "E876 HIPOPOTASEMIA", "FIEBRE PERSISTENTE"]
        assert df["cie10_mapeado"].tolist()[:5] == [True, True, True, True, False]
        assert pd.isna(df.loc[5, "cie10"]) and pd.isna(df.loc[5, "cie10_mapeado"])
        # Assert: conteos
        assert regla(BLOQUE, "sin pareja") == (5, 1)
        filas = {r: v["filas_afectadas"] for (_, _, r), v in reporte.correcciones.items()}
        assert filas["error ortografico corregido antes de mapear"] == 1
        assert filas["texto llevado a la linea CIE-10 de REDCap (equivalencia revisada)"] == 1
        assert filas["texto llevado a la linea CIE-10 de REDCap (coincidencia exacta)"] == 3
        assert filas["asignado a la version sin simbolo (REDCap tambien la ofrece con * o †)"] == 1
        reporte.verificar_auditoria()

    def test_equivalencia_hacia_linea_inexistente_falla(self, catalogo, reporte):
        """
        Qué es: prueba unitaria de la validación de equivalencias revisadas.
        Qué hace: usa una equivalencia que apunta a una línea que no está en el catálogo.
        Esperado: ValueError antes de modificar el DataFrame.
        """
        # Arrange
        df = pd.DataFrame({"cie10": ["x"]})
        ajustes = {"correcciones_texto": {}, "equivalencias": {"x": "Z99 NO EXISTE"}}

        # Act + Assert
        with pytest.raises(ValueError, match="no están en el catálogo"):
            mapear_texto_a_cie10(df, reporte, BLOQUE, "cie10", "cie10_mapeado", catalogo, ajustes)
        assert df["cie10"].tolist() == ["x"]


class TestUnificarEtiquetasCanonicasRedcap:
    def test_reasigna_solo_la_redaccion_alterna(self, rutas, reporte):
        """
        Qué es: prueba unitaria de unificar_etiquetas_canonicas (REDCap, decisión 7.2).
        Qué hace: unifica una columna con la redacción alterna de R31, la canónica, otra línea con símbolo y un vacío,
                  e incluye una columna ausente en la lista.
        Esperado: solo la alterna cambia (1 corrección); el símbolo y el vacío se conservan; la columna ausente se omite.
        """
        # Arrange
        alternas = redacciones_alternas(*rutas)
        df = pd.DataFrame({"cie_10_comorbilidades": ["R31 HEMATURIA NO ESPECIFICADA", "R31 HEMATURIA, NO ESPECIFICADA",
                                               "F001* DEMENCIA EN LA ENFERMEDAD DE ALZHEIMER DE COMIENZO TARDIO", None]})

        # Act
        unificar_etiquetas_canonicas(df, reporte, "comorbilidades", ["cie_10_comorbilidades", "ausente"], alternas)

        # Assert
        assert df["cie_10_comorbilidades"].tolist()[:3] == ["R31 HEMATURIA, NO ESPECIFICADA"] * 2 + [
            "F001* DEMENCIA EN LA ENFERMEDAD DE ALZHEIMER DE COMIENZO TARDIO"]
        assert pd.isna(df.loc[3, "cie_10_comorbilidades"])
        assert [v["filas_afectadas"] for v in reporte.correcciones.values()] == [1]

    @pytest.mark.parametrize("modulo, columna", [
        (comorbilidades, "cie_10_comorbilidades"),
        (cie_10_diagnosticos, "cie_10_diagnostico_definitivo"),
        (complicaciones, "cie_10_complicaciones_de_hospitalizacion"),
    ])
    def test_instrumentos_redcap_unifican_su_columna(self, modulo, columna, reporte):
        """
        Qué es: prueba unitaria de los módulos de REDCap con CIE-10 (comorbilidades, cie_10_diagnosticos y
                complicaciones), con el catálogo real.
        Qué hace: transforma un bloque sintético con la redacción alterna de R31.
        Esperado: la columna CIE-10 del instrumento pasa a la etiqueta canónica y la corrección queda registrada.
        """
        # Arrange
        df = pd.DataFrame({"record_id": ["1"], columna: ["R31 HEMATURIA NO ESPECIFICADA"]})

        # Act
        resultado = modulo.transformar(df, reporte, {})

        # Assert
        assert resultado.loc[0, columna] == "R31 HEMATURIA, NO ESPECIFICADA"
        assert (modulo.NOMBRE, columna) in {(b, c) for (b, c, _) in reporte.correcciones}


LINEAS_CATALOGO_LISTA = [
    "X93 AGRESION CON DISPARO DE ARMA CORTA",
    "X930 AGRESION CON DISPARO DE ARMA CORTA: VIVIENDA",
    "W01 CAIDA EN EL MISMO NIVEL POR DESLIZAMIENTO",
]
LINEAS_LISTA = [
    "X93 AGRESION CON DISPARO DE ARMA CORTA",
    "X930 AGRESION CON DISPARO DE A",                                    # misma clave del catálogo, etiqueta cortada
    "X931 AGRESION CON DISPARO DE ARMA CORTA: INSTITUCION RESI",         # cortada a ~60 caracteres
    "W011 CAIDA EN EL MISMO NIVEL POR DESLIZAMIENTO, TROPEZON O",        # dos códigos con la misma etiqueta cortada
    "W012 CAIDA EN EL MISMO NIVEL POR DESLIZAMIENTO, TROPEZON O",
    "S720 FRACTURA DEL CUELLO DEL FEMUR",                                # solo existe en la lista, etiqueta completa
    "S722 FRACTURA SUBTROCANTERIANA DEL FEMUR",
]


@pytest.fixture
def universo(tmp_path):
    """
    Universo CIE-10 sintético: un catálogo de 3 líneas con etiqueta completa y una lista completa de 7 líneas con el
    defecto de la real (etiquetas cortadas a ~60 caracteres y códigos hermanos con la misma etiqueta cortada), en una
    carpeta temporal. Aislado de los archivos reales y sin datos de pacientes.
    """
    cat = tmp_path / "cat.csv"
    pd.DataFrame({"codigo_cie10": LINEAS_CATALOGO_LISTA}).to_csv(cat, index=False, encoding="utf-8")
    canon = tmp_path / "canon.yaml"
    canon.write_text("etiquetas_canonicas: {}\n", encoding="utf-8")
    lista = tmp_path / "lista.csv"
    pd.DataFrame({"indice": range(1, len(LINEAS_LISTA) + 1), "linea": LINEAS_LISTA}).to_csv(
        lista, index=False, encoding="utf-8")
    return cargar_universo(cargar_catalogo(cat, canon), lista)


class TestUniversoCie10:
    def test_el_catalogo_gana_y_la_lista_agrega_los_codigos_nuevos(self, universo):
        """
        Qué es: prueba unitaria de cargar_universo (catálogo + lista completa de REDCap).
        Qué hace: carga el universo sintético, donde X93 y X930 están en el catálogo y en la lista (X930 con etiqueta
                  cortada en la lista).
        Esperado: 8 líneas (3 del catálogo + 5 solo de la lista); X930 conserva la etiqueta completa del catálogo; solo
                  son `truncada` las líneas solo-lista de 55 caracteres o más.
        """
        # Arrange + Act: universo de la fixture
        lineas = set(universo["linea"])

        # Assert
        assert len(universo) == 3 + 5
        assert "X930 AGRESION CON DISPARO DE ARMA CORTA: VIVIENDA" in lineas
        assert "X930 AGRESION CON DISPARO DE A" not in lineas
        truncadas = set(universo.loc[universo["truncada"], "codigo"])
        assert truncadas == {"X931", "W011", "W012"}

    def test_lista_real_carga_y_trae_los_codigos_de_lugar(self):
        """
        Qué es: prueba de integridad de la lista completa real (config/catalogos/cie10_lista_completa.csv, solo
                códigos y etiquetas de CIE-10).
        Qué hace: carga el universo real.
        Esperado: más de 14 000 códigos, incluidos los de la familia X93 (agresión con arma corta según lugar).
        """
        # Arrange + Act
        universo = cargar_universo()

        # Assert
        assert len(universo) > 14000
        assert {"X930", "X939"} <= set(universo["codigo"])


class TestBuscarCandidatos:
    def test_tipos_de_coincidencia(self, universo):
        """
        Qué es: prueba unitaria de buscar_candidatos (apoyo a la revisión manual de los textos sin pareja).
        Qué hace: busca seis textos sintéticos: «, en vivienda» de un código completo, un lugar cuya etiqueta está cortada,
                  un texto con detalle de un código general, dos códigos con la misma etiqueta cortada, un texto abreviado
                  y uno sin parecido.
        Esperado: exacta (propuesta X930); etiqueta_cortada con propuesta X931; general (W01); etiqueta_cortada con 2
                  candidatos y sin propuesta; texto_abreviado (S722); sin_candidato.
        """
        # Arrange
        textos = ["Agresión con disparo de arma corta, en vivienda",
                  "Agresión con disparo de arma corta, en institución residencial",
                  "Caída en el mismo nivel por deslizamiento, en calles",
                  "Caída en el mismo nivel por deslizamiento, tropezón o traspié",
                  "Fractura subtrocanteriana del",
                  "Texto que no existe"]

        # Act
        r = buscar_candidatos(textos, universo).set_index("texto")

        # Assert
        assert (r.loc[textos[0], "tipo"], r.loc[textos[0], "propuesta"]) == (
            "exacta", "X930 AGRESION CON DISPARO DE ARMA CORTA: VIVIENDA")
        assert (r.loc[textos[1], "tipo"], r.loc[textos[1], "propuesta"][:4]) == ("etiqueta_cortada", "X931")
        assert (r.loc[textos[2], "tipo"], r.loc[textos[2], "propuesta"][:3]) == ("general", "W01")
        assert (r.loc[textos[3], "tipo"], r.loc[textos[3], "n_candidatos"], r.loc[textos[3], "propuesta"]) == (
            "etiqueta_cortada", 2, "")
        assert (r.loc[textos[4], "tipo"], r.loc[textos[4], "propuesta"][:4]) == ("texto_abreviado", "S722")
        assert r.loc[textos[5], "tipo"] == "sin_candidato"
        assert r.loc[textos[0], "candidato_general"].startswith("X93 ")

    def test_los_capitulos_limitan_los_codigos(self, universo):
        """
        Qué es: prueba unitaria de la restricción por capítulos de buscar_candidatos.
        Qué hace: busca la misma agresión con capítulos "W" (que no incluye a X93).
        Esperado: sin_candidato, porque el campo no admite esos códigos.
        """
        # Arrange + Act
        r = buscar_candidatos(["Agresión con disparo de arma corta, en vivienda"], universo, "W")

        # Assert
        assert r.loc[0, "tipo"] == "sin_candidato"


class TestMapearConListaCompleta:
    def test_aplica_solo_la_coincidencia_exacta_y_audita(self, universo, reporte):
        """
        Qué es: prueba unitaria de mapear_texto_a_cie10 con el universo (lista completa de REDCap).
        Qué hace: mapea cuatro textos sintéticos: «, en vivienda» de un código del catálogo, un código solo de la lista
                  con etiqueta completa, un texto con dos candidatos de etiqueta cortada y uno sin parecido.
        Esperado: los dos primeros pasan a su línea (2 por la lista completa, 0 por el catálogo); los otros quedan en
                  MAYÚSCULAS con marca False; la auditoría conserva.
        """
        # Arrange: el catálogo son las líneas del universo que vienen del catálogo
        df = pd.DataFrame({"cie10": ["Agresión con disparo de arma corta, en vivienda", "Fractura del cuello del fémur",
                                     "Caída en el mismo nivel por deslizamiento, tropezón o traspié", "Texto sin pareja"]})
        catalogo = universo[universo["linea"].isin(LINEAS_CATALOGO_LISTA)]

        # Act
        pares = mapear_texto_a_cie10(df, reporte, BLOQUE, "cie10", "cie10_mapeado", catalogo=catalogo,
                                     ajustes={"correcciones_texto": {}, "equivalencias": {}}, universo=universo)

        # Assert
        assert df["cie10"].tolist() == [
            "X930 AGRESION CON DISPARO DE ARMA CORTA: VIVIENDA", "S720 FRACTURA DEL CUELLO DEL FEMUR",
            "CAÍDA EN EL MISMO NIVEL POR DESLIZAMIENTO, TROPEZÓN O TRASPIÉ", "TEXTO SIN PAREJA"]
        assert df["cie10_mapeado"].tolist() == [True, True, False, False]
        filas = {r: v["filas_afectadas"] for (_, _, r), v in reporte.correcciones.items()}
        assert filas["texto llevado a la linea CIE-10 de REDCap (lista completa, coincidencia exacta)"] == 2
        assert filas["texto llevado a la linea CIE-10 de REDCap (coincidencia exacta)"] == 0
        # Assert: las parejas devueltas para revisión (texto original, resultado y método)
        assert pares["metodo"].tolist().count("lista_completa_exacta") == 2
        assert pares.set_index("texto_excel").loc["Texto sin pareja", "metodo"] == "sin_pareja"
        assert pares["n_filas"].sum() == 4
        reporte.verificar_auditoria()


class TestCandidatosSinPareja:
    def test_agrupa_por_campo_y_deja_la_decision_vacia(self, universo):
        """
        Qué es: prueba unitaria de candidatos_sin_pareja (insumo del CSV de revisión de los textos sin pareja).
        Qué hace: arma una hoja sintética con filas mapeadas y sin pareja de dos campos (uno con capítulos V a Y y otro
                  libre) y pide los candidatos.
        Esperado: solo salen los textos sin pareja, una vez cada uno con su número de filas; el campo de causas externas
                  propone X930 y el campo libre encuentra S720; `decision` queda vacía.
        """
        # Arrange
        otros = "cie_10_otros_mecanismos_de_lesion_excluye_transito"
        df = pd.DataFrame({
            "cie10": ["AGRESIÓN CON DISPARO DE ARMA CORTA, EN VIVIENDA"] * 2 + ["FRACTURA DEL CUELLO DEL FEMUR", "I46 PARO"],
            "campo_redcap": [otros, otros, "cie_10_comorbilidades", "cie_10_comorbilidades"],
            "cie10_mapeado": pd.array([False, False, False, True], dtype="boolean"),
        })

        # Act
        r = candidatos_sin_pareja(df, "cie10", "cie10_mapeado", universo, "campo_redcap")

        # Assert
        assert len(r) == 2
        por_campo = r.set_index("campo_redcap")
        assert por_campo.loc[otros, "n_filas"] == 2
        assert por_campo.loc[otros, "propuesta"].startswith("X930 ")
        assert por_campo.loc["cie_10_comorbilidades", "propuesta"].startswith("S720 ")
        assert (r["decision"] == "").all()
