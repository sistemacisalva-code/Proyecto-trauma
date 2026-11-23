import pandas as pd
import pytest

from etl.transform.common.lugar_del_evento import cargar_reglas, mapear_lugar_del_evento

BLOQUE = "identificadores_pendientes"
COL = "lugar_del_evento"
YAML_MINIMO = """
etiqueta_sin_clasificar: Lugar no especificado
etiquetas: [Calles y avenidas, Domicilio, Lugar no especificado, Área de servicio médico]
reglas:
  - etiqueta: Área de servicio médico
    palabras: [hospital, clinica, centro de salud]
  - etiqueta: Domicilio
    palabras: [casa, apartamento]
  - etiqueta: Calles y avenidas
    palabras: [calle, carrera]
  - etiqueta: Calles y avenidas
    palabras: [cl, cra]
"""


@pytest.fixture
def reglas_sinteticas(tmp_path):
    """
    Reglas de lugar_del_evento sintéticas y mínimas (4 etiquetas, una de ellas con una regla de abreviaturas al
    final) en un YAML temporal. Aislado del YAML real y sin datos de pacientes.
    """
    ruta = tmp_path / "lugar.yaml"
    ruta.write_text(YAML_MINIMO, encoding="utf-8")
    return cargar_reglas(ruta)


class TestMapearLugarDelEvento:
    def test_prioridad_frases_plurales_y_abreviaturas(self, reglas_sinteticas, reporte):
        """
        Qué es: prueba unitaria de mapear_lugar_del_evento (Excel) con reglas sintéticas.
        Qué hace: clasifica cinco textos inventados: dos palabras clave de reglas distintas en un mismo texto, una frase
                  de varias palabras, un plural, una abreviatura y una palabra que contiene a otra ("casino").
        Esperado: gana la regla de mayor prioridad (hospital sobre calle); la frase y el plural coinciden; la
                  abreviatura asigna calle; "casino" no coincide con "casa" (comparación por palabra completa).
        """
        # Arrange
        df = pd.DataFrame({COL: ["hospital en la calle", "Centro de Salud", "clínicas", "cra", "casino"]})

        # Act
        mapear_lugar_del_evento(df, reporte, BLOQUE, COL, reglas_sinteticas)

        # Assert
        assert df[COL].tolist() == ["Área de servicio médico", "Área de servicio médico", "Área de servicio médico",
                                    "Calles y avenidas", "Lugar no especificado"]

    def test_sin_palabra_clave_queda_sin_especificar_y_se_audita(self, reglas_sinteticas, reporte, regla):
        """
        Qué es: prueba unitaria del tratamiento de lo que no se puede clasificar.
        Qué hace: clasifica un domicilio, un nombre propio sin palabra clave, un "lugar no especificado" que ya venía
                  así y un vacío.
        Esperado: el nombre propio queda como «Lugar no especificado» y se devuelve en la lista de sin clasificar; la
                  regla evalúa 3 informados y 1 incumple (el que ya venía sin especificar no cuenta); el vacío
                  sigue vacío; la auditoría conserva.
        """
        # Arrange
        df = pd.DataFrame({COL: ["casa", "conjunto los robles", "lugar no especificado", None]})

        # Act
        sin_clasificar = mapear_lugar_del_evento(df, reporte, BLOQUE, COL, reglas_sinteticas)

        # Assert
        assert df[COL].tolist()[:3] == ["Domicilio", "Lugar no especificado", "Lugar no especificado"]
        assert pd.isna(df.loc[3, COL])
        assert sin_clasificar.tolist() == ["conjunto los robles"]
        assert regla(BLOQUE, "sin palabra clave") == (3, 1)
        filas = {r: v["filas_afectadas"] for (_, _, r), v in reporte.correcciones.items()}
        assert filas["texto llevado a la etiqueta de REDCap «Domicilio» (palabra clave)"] == 1
        reporte.verificar_auditoria()

    def test_etiqueta_fuera_del_dominio_falla(self, tmp_path):
        """
        Qué es: prueba unitaria de la validación de cargar_reglas.
        Qué hace: carga un YAML con una regla hacia una etiqueta que no está en el dominio de REDCap.
        Esperado: ValueError, para no introducir una opción que REDCap no ofrece.
        """
        # Arrange
        malo = tmp_path / "malo.yaml"
        malo.write_text(YAML_MINIMO.replace("etiqueta: Domicilio", "etiqueta: Plaza inventada"), encoding="utf-8")

        # Act + Assert
        with pytest.raises(ValueError, match="fuera del dominio"):
            cargar_reglas(malo)


class TestReglasRealesLugarDelEvento:
    @pytest.mark.parametrize("texto, esperado", [
        ("cancha de futbol", "Áreas atléticas y de deporte"),
        ("aeropuerto", "Área comercial/servicio"),
        ("Alfonso Bonilla Aragón", "Área comercial/servicio"),
        ("colegio", "Escuela"),
        ("calle", "Calles y avenidas"),
        ("ca", "Calles y avenidas"),
        ("casa", "Domicilio"),
        ("finca", "Haciendas"),
        ("rio", "Mar, lago, río, embalse, pozo"),
        ("playa", "Tierra abierta, playa, bosque, desierto"),
        ("obra", "Áreas de servicio y de construcción"),
        ("alcaldía", "Área administrativa publica"),
        ("clínica", "Área de servicio médico"),
        ("nombre sin palabra de contexto", "Lugar no especificado"),
    ])
    def test_el_yaml_real_clasifica_las_palabras_de_contexto(self, texto, esperado, reporte):
        """
        Qué es: prueba de integridad del YAML real (config/catalogos/lugar_del_evento.yaml, solo palabras de contexto).
        Qué hace: carga las reglas reales y clasifica un texto inventado por cada etiqueta del dominio de REDCap.
        Esperado: cada texto va a su etiqueta; todas las etiquetas del YAML pertenecen al dominio de 12 etiquetas.
        """
        # Arrange
        reglas = cargar_reglas()
        df = pd.DataFrame({COL: [texto]})

        # Act
        mapear_lugar_del_evento(df, reporte, BLOQUE, COL, reglas)

        # Assert
        assert len(reglas["etiquetas"]) == 12
        assert df.loc[0, COL] == esperado
