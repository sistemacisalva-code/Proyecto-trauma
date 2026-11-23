import pandas as pd
import pytest

from etl.transform.redcap.instrumentos import informacion_demografica as demografica
from etl.transform.redcap.instrumentos.informacion_demografica import NOMBRE, SEGURO_SIN_INFORMAR, transformar


@pytest.fixture
def demografico():
    """
    Bloque demográfico sintético de tres episodios (texto, como llega del export): dos con datos y uno
    con fecha, edad y género ausentes. El seguro va informado en dos y vacío en uno, para la etiqueta que REDCap adopta
    del Excel. Valores inventados; sin datos reales.
    """
    return pd.DataFrame({
        "record_id": ["1", "2", "3"],
        "fecha_y_hora_de_llegada_del_paciente": ["2024-01-10 08:30", "2024-02-01 20:00", None],
        "edad": ["34", "87", None],
        "genero": ["M", "F", None],
        "tipo_de_seguro": ["SEGURO-SINTETICO-A", None, "SEGURO-SINTETICO-B"],
    })


class TestInstrumentoDemografica:
    def test_tipos_derivadas_y_eliminacion_de_la_edad(self, demografico, reporte):
        """
        Qué es: prueba unitaria de la transformación del bloque demográfico (caso normal).
        Qué hace: transforma el bloque sintético con un episodio sin datos.
        Esperado: la llegada pasa a datetime, aparecen quinquenio_edad y quinquenio_orden (Int64) con nulo donde
                  no hay edad, la edad exacta se elimina, y la auditoría conserva todo.
        """
        # Arrange: bloque sintético del fixture

        # Act: transformar
        resultado = transformar(demografico, reporte, {})

        # Assert: columnas, tipos y valores derivados
        assert list(resultado.columns) == ["record_id", "fecha_y_hora_de_llegada_del_paciente", "genero",
                                           "tipo_de_seguro", "quinquenio_edad", "quinquenio_orden"]
        assert pd.api.types.is_datetime64_any_dtype(resultado["fecha_y_hora_de_llegada_del_paciente"])
        assert resultado["quinquenio_edad"].iloc[:2].tolist() == ["30-34", "85 o más"]
        assert resultado["quinquenio_orden"].iloc[:2].tolist() == [6, 17]
        assert str(resultado["quinquenio_orden"].dtype) == "Int64"
        assert resultado[["quinquenio_edad", "quinquenio_orden"]].isna().iloc[2].all()
        reporte.verificar_auditoria()

    def test_edad_fuera_de_rango_se_invalida_y_se_cuenta(self, demografico, reporte):
        """
        Qué es: prueba unitaria del dominio de la edad [0, 120].
        Qué hace: cambia la edad del episodio 2 por 121.
        Esperado: la edad se invalida (sin quinquenio para ese episodio) y la auditoría cuenta 1 fuera de rango,
                  sin pérdidas sin explicar.
        """
        # Arrange: una edad imposible
        demografico.loc[1, "edad"] = "121"

        # Act: transformar
        resultado = transformar(demografico, reporte, {})

        # Assert: invalidada y contada
        assert pd.isna(resultado.loc[1, "quinquenio_edad"])
        assert reporte.auditoria[(NOMBRE, "edad")]["fuera_de_rango"] == 1
        reporte.verificar_auditoria()

    def test_el_seguro_vacio_queda_con_la_etiqueta_del_excel_y_se_cuenta(self, demografico, reporte):
        """
        Qué es: prueba unitaria de la etiqueta del seguro no informado en REDCap (2026-10-31).
        Qué hace: transforma el bloque sintético, que trae un episodio con `tipo_de_seguro` vacío.
        Esperado: ese episodio queda con 'No especificado' (la etiqueta del Excel), los informados no se tocan y la
                  corrección queda contada en el reporte con la acción 'completado'.
        """
        # Arrange: bloque sintético del fixture (el episodio 2 sin seguro)

        # Act
        resultado = transformar(demografico, reporte, {})

        # Assert: solo el vacío cambia, y el cambio queda contado
        assert resultado["tipo_de_seguro"].tolist() == ["SEGURO-SINTETICO-A", SEGURO_SIN_INFORMAR,
                                                        "SEGURO-SINTETICO-B"]
        correccion = reporte.correcciones[(NOMBRE, "tipo_de_seguro",
                                           f"seguro vacio etiquetado como '{SEGURO_SIN_INFORMAR}' (dominio del Excel)")]
        assert (correccion["filas_afectadas"], correccion["accion"]) == (1, "completado")

    def test_edad_decimal_detiene_la_ejecucion(self, demografico, reporte):
        """
        Qué es: prueba unitaria del contrato entero de la edad.
        Qué hace: pone una edad con decimales.
        Esperado: ValueError que menciona "enteros": el origen cambió y no se corrige en silencio.
        """
        # Arrange: edad decimal
        demografico.loc[0, "edad"] = "34.5"

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="enteros"):
            transformar(demografico, reporte, {})

    def test_episodio_repetido_detiene_la_ejecucion(self, demografico, reporte):
        """
        Qué es: prueba unitaria de la verificación del grano episodio.
        Qué hace: repite un record_id en el bloque demográfico.
        Esperado: ValueError por clave no única (el instrumento no es repetible).
        """
        # Arrange: el episodio 1 repetido
        repetido = pd.concat([demografico, demografico.iloc[[0]]], ignore_index=True)

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="no es única"):
            transformar(repetido, reporte, {})

    def test_contrato_del_modulo(self):
        """
        Qué es: prueba del contrato de instrumento del módulo demográfico.
        Qué hace: revisa NOMBRE, CATEGORICAS y que el módulo expone transformar.
        Esperado: NOMBRE es el del instrumento; las categóricas incluyen género y no incluyen la edad
                  (que se elimina) ni identificadores.
        """
        # Arrange: el módulo importado

        # Act: no aplica, se inspeccionan sus constantes

        # Assert: contrato
        assert demografica.NOMBRE == "informacion_demografica"
        assert "genero" in demografica.CATEGORICAS
        assert "edad" not in demografica.CATEGORICAS
        assert callable(demografica.transformar)
