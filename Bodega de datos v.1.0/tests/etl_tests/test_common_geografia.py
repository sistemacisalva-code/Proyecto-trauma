import pandas as pd
import pytest

from etl.transform.common.geografia import (
    DEPARTAMENTOS,
    cargar_catalogo,
    cargar_catalogo_departamentos,
    clasificar_departamentos,
    clasificar_municipios,
    completar_departamento,
    departamento_por_municipio,
    estandarizar_municipios,
    normalizar_texto,
)

YAML_BASE = """
municipios:
  - municipio: Cali
    departamento: Valle del Cauca
    variantes: [cali, santiago de cali]
  - municipio: Dagua
    departamento: Valle del Cauca
    confianza: media
    variantes: [dagua]
  - municipio: Bolívar
    departamento: Sin determinar
    variantes: [bolivar]
sin_municipio:
  departamentos:
    - {valor: Cauca, variantes: [cauca]}
  sin_informacion: [sd]
  no_identificables: [camilo]
departamentos:
  - {nombre: Cauca, variantes: [cauca]}
  - {nombre: Nariño, variantes: [narino, pasto]}
"""


@pytest.fixture
def ruta_catalogo(tmp_path):
    """
    Catálogo YAML sintético y mínimo (tres municipios, un departamento escrito como lugar, un valor sin información
    y uno no identificable), escrito en una carpeta temporal. Aísla las pruebas del catálogo real de config/ y no
    contiene ningún dato de pacientes.
    """
    ruta = tmp_path / "estandar_municipios.yaml"
    ruta.write_text(YAML_BASE, encoding="utf-8")
    return ruta


class TestNormalizarTexto:
    def test_quita_tildes_signos_y_espacios_sobrantes(self):
        """
        Qué es: prueba unitaria de normalizar_texto (llave de comparación del catálogo).
        Qué hace: normaliza mayúsculas, tildes, signos y espacios repetidos.
        Esperado: minúsculas, sin tildes ni signos y con un solo espacio entre palabras.
        """
        # Arrange + Act: valores con las variaciones de escritura que trae el Excel
        resultado = [normalizar_texto(v) for v in ["  Bogotá, D.C. ", "SANTIAGO   DE CALI", "Nariño"]]

        # Assert: misma forma para variantes equivalentes
        assert resultado == ["bogota d c", "santiago de cali", "narino"]


class TestCargarCatalogo:
    def test_carga_variantes_normalizadas_con_su_tipo(self, ruta_catalogo):
        """
        Qué es: prueba unitaria de cargar_catalogo.
        Qué hace: carga el catálogo sintético y consulta una variante de municipio, un departamento, un valor sin
                  información y uno no identificable.
        Esperado: cada variante normalizada apunta a su tipo y confianza (la omitida es alta).
        """
        # Arrange: catálogo sintético en disco

        # Act: cargar
        cat = cargar_catalogo(ruta_catalogo)

        # Assert: tipos y confianza esperados
        assert cat["santiago de cali"]["municipio"] == "Cali" and cat["santiago de cali"]["confianza"] == "alta"
        assert cat["dagua"]["confianza"] == "media"
        assert cat["cauca"]["tipo"] == "solo_departamento"
        assert cat["sd"]["tipo"] == "sin_informacion"
        assert cat["camilo"]["tipo"] == "no_identificable"

    def test_variante_repetida_con_destinos_distintos_falla(self, tmp_path):
        """
        Qué es: prueba unitaria de la validación del catálogo.
        Qué hace: carga un YAML donde la misma variante apunta a dos municipios distintos.
        Esperado: ValueError que nombra la variante, para no clasificar con un destino ambiguo.
        """
        # Arrange: la variante "cali" en dos municipios
        ruta = tmp_path / "ambiguo.yaml"
        ruta.write_text("""
municipios:
  - {municipio: Cali, departamento: Valle del Cauca, variantes: [cali]}
  - {municipio: Calima, departamento: Valle del Cauca, variantes: [cali]}
sin_municipio: {departamentos: [], sin_informacion: [], no_identificables: []}
""", encoding="utf-8")

        # Act + Assert: la carga se detiene
        with pytest.raises(ValueError, match="Variante repetida"):
            cargar_catalogo(ruta)

    def test_departamento_fuera_del_dominio_falla(self, tmp_path):
        """
        Qué es: prueba unitaria de la validación del catálogo.
        Qué hace: carga un municipio cuyo departamento no pertenece a los 33 oficiales.
        Esperado: ValueError que nombra el departamento inválido.
        """
        # Arrange: departamento inexistente
        ruta = tmp_path / "invalido.yaml"
        ruta.write_text("""
municipios:
  - {municipio: Cali, departamento: Valle, variantes: [cali]}
sin_municipio: {departamentos: [], sin_informacion: [], no_identificables: []}
""", encoding="utf-8")

        # Act + Assert
        with pytest.raises(ValueError, match="fuera del dominio"):
            cargar_catalogo(ruta)

    def test_catalogo_real_es_consistente(self):
        """
        Qué es: prueba de integridad del catálogo real (config/estandar_municipios.yaml), que solo contiene nombres.
        Qué hace: carga los catálogos de municipios y de departamentos y el mapa municipio → departamento.
        Esperado: carga sin error (sin variantes ambiguas, con departamentos del dominio) y todo departamento del
                  mapa pertenece a los 33 oficiales en mayúsculas.
        """
        # Arrange: catálogo real por defecto

        # Act: cargar los tres insumos
        cargar_catalogo()
        cargar_catalogo_departamentos()
        mapa = departamento_por_municipio()

        # Assert: dominio de departamentos respetado
        oficiales = {d.upper() for d in DEPARTAMENTOS}
        assert mapa and set(mapa.values()) <= oficiales


class TestClasificarMunicipios:
    def test_clasifica_cada_tipo_de_valor(self, ruta_catalogo):
        """
        Qué es: prueba unitaria de clasificar_municipios.
        Qué hace: clasifica un municipio, un departamento escrito como lugar, un valor sin información, uno no
                  identificable, un nulo, un valor fuera del catálogo y un texto de solo signos.
        Esperado: municipio en MAYÚSCULAS solo para el municipio; el resto queda vacío con su tipo; el índice se conserva.
        """
        # Arrange: una fila por caso, con índice no consecutivo para comprobar el alineamiento
        serie = pd.Series(["Santiago de Cali", "CAUCA", "sd", "Camilo", None, "xyz", "..."],
                          index=[10, 11, 12, 13, 14, 15, 16])

        # Act: clasificar con el catálogo sintético
        res = clasificar_municipios(serie, cargar_catalogo(ruta_catalogo))

        # Assert: tipos, municipio y confianza; índice intacto
        assert res["tipo"].tolist() == ["municipio", "solo_departamento", "sin_informacion", "no_identificable",
                                        "nulo", "sin_clasificar", "sin_informacion"]
        assert res.loc[10, "municipio"] == "CALI"
        assert res["municipio"].drop(10).isna().all()
        assert list(res.index) == [10, 11, 12, 13, 14, 15, 16]

    def test_estandarizar_devuelve_el_municipio_con_el_nombre_de_la_serie(self, ruta_catalogo):
        """
        Qué es: prueba unitaria de estandarizar_municipios.
        Qué hace: estandariza dos valores, uno del catálogo y uno ajeno.
        Esperado: "CALI" y NA, y la serie resultante conserva el nombre de la entrada.
        """
        # Arrange
        serie = pd.Series(["cali", "otro lugar"], name="ciudad")

        # Act
        resultado = estandarizar_municipios(serie, cargar_catalogo(ruta_catalogo))

        # Assert: valor oficial, vacío para lo desconocido y nombre conservado
        assert resultado.iloc[0] == "CALI" and pd.isna(resultado.iloc[1])
        assert resultado.name == "ciudad"


class TestClasificarDepartamentos:
    def test_clasifica_departamento_nulo_y_sin_clasificar(self, ruta_catalogo):
        """
        Qué es: prueba unitaria de clasificar_departamentos.
        Qué hace: clasifica una variante del catálogo, un departamento escrito con tilde y mayúsculas, un nulo,
                  un texto vacío y un valor ajeno (otro país).
        Esperado: nombre oficial en MAYÚSCULAS para los del catálogo; NA con tipo nulo o sin_clasificar para el resto.
        """
        # Arrange: catálogo de departamentos sintético
        catalogo = cargar_catalogo_departamentos(ruta_catalogo)
        serie = pd.Series(["Pasto", "NARIÑO", None, "  ", "Ecuador"])

        # Act
        res = clasificar_departamentos(serie, catalogo)

        # Assert
        assert res["tipo"].tolist() == ["departamento", "departamento", "nulo", "nulo", "sin_clasificar"]
        assert res["departamento"].iloc[:2].tolist() == ["NARIÑO", "NARIÑO"]
        assert res["departamento"].iloc[2:].isna().all()

    def test_departamento_fuera_del_dominio_falla(self, tmp_path):
        """
        Qué es: prueba unitaria de la validación del catálogo de departamentos.
        Qué hace: carga un catálogo con un departamento que no es oficial.
        Esperado: ValueError, para no introducir un valor fuera del dominio de la dimensión.
        """
        # Arrange
        ruta = tmp_path / "deptos.yaml"
        ruta.write_text("departamentos:\n  - {nombre: Atlantida, variantes: [atlantida]}\n", encoding="utf-8")

        # Act + Assert
        with pytest.raises(ValueError, match="fuera del dominio"):
            cargar_catalogo_departamentos(ruta)


class TestCompletarDepartamento:
    def test_mapa_usa_solo_confianza_alta_y_departamento_determinado(self, ruta_catalogo):
        """
        Qué es: prueba unitaria de departamento_por_municipio.
        Qué hace: construye el mapa desde el catálogo sintético, que trae un municipio de confianza alta, otro de
                  confianza media y otro con departamento "Sin determinar".
        Esperado: solo el de confianza alta, en MAYÚSCULAS; los supuestos o ambiguos no se usan para inferir.
        """
        # Arrange: catálogo sintético

        # Act
        mapa = departamento_por_municipio(ruta_catalogo)

        # Assert
        assert mapa == {"CALI": "VALLE DEL CAUCA"}

    def test_municipio_con_dos_departamentos_falla(self, tmp_path):
        """
        Qué es: prueba unitaria de la validación del mapa municipio → departamento.
        Qué hace: carga dos entradas de confianza alta del mismo municipio con departamentos distintos.
        Esperado: ValueError que nombra el municipio.
        """
        # Arrange
        ruta = tmp_path / "dos_deptos.yaml"
        ruta.write_text("""
municipios:
  - {municipio: Bolivar, departamento: Cauca, variantes: [bolivar cauca]}
  - {municipio: Bolivar, departamento: Valle del Cauca, variantes: [bolivar valle]}
""", encoding="utf-8")

        # Act + Assert
        with pytest.raises(ValueError, match="dos departamentos"):
            departamento_por_municipio(ruta)

    def test_completa_solo_vacios_con_confianza_alta(self):
        """
        Qué es: prueba unitaria de completar_departamento.
        Qué hace: intenta completar cinco filas: vacío con confianza alta, vacío con confianza media, ya informado,
                  vacío con alta y vacío sin municipio.
        Esperado: se rellenan solo la primera y la cuarta; nunca se sobrescribe un departamento informado.
        """
        # Arrange: mapa y columnas sintéticas
        mapa = {"CALI": "VALLE DEL CAUCA", "DAGUA": "VALLE DEL CAUCA"}
        municipio = pd.Series(["CALI", "DAGUA", "CALI", "CALI", None], dtype="string")
        departamento = pd.Series([pd.NA, pd.NA, "CAUCA", pd.NA, pd.NA], dtype="string")
        confianza = pd.Series(["alta", "media", "alta", "alta", "alta"])

        # Act
        completo, rellenadas = completar_departamento(municipio, departamento, confianza, mapa)

        # Assert: máscara y valores
        assert rellenadas.tolist() == [True, False, False, True, False]
        assert completo.iloc[[0, 3]].tolist() == ["VALLE DEL CAUCA", "VALLE DEL CAUCA"]
        assert completo.iloc[2] == "CAUCA"
        assert completo.iloc[[1, 4]].isna().all()
