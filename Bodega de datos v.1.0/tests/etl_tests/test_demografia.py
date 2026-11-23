import pandas as pd
import pytest

from etl.transform.common.demografia import (
    MAPEO_ORDEN,
    MAPEO_QUINQUENIOS,
    derivar_quinquenios,
    edad_en_anios_cumplidos,
    quinquenio,
    quinquenio_orden,
)

BLOQUE = "bloque_sintetico"


class TestQuinquenio:
    @pytest.mark.parametrize("edad, esperado", [
        (0, "0-4"), (4, "0-4"), (5, "5-9"), (34, "30-34"), (84, "80-84"), (85, "85 o más"), (120, "85 o más"),
    ])
    def test_etiqueta_del_quinquenio(self, edad, esperado):
        """
        Qué es: prueba unitaria de quinquenio (etiqueta por edad).
        Qué hace: calcula la etiqueta de edades en los bordes de cada tramo (7 casos).
        Esperado: tramos de 5 años hasta "80-84" y "85 o más" desde los 85.
        """
        # Arrange: edad parametrizada

        # Act: calcular
        etiqueta = quinquenio(edad)

        # Assert: etiqueta esperada
        assert etiqueta == esperado

    @pytest.mark.parametrize("edad, esperado", [(0, 0), (4, 0), (5, 1), (34, 6), (84, 16), (85, 17), (120, 17)])
    def test_posicion_del_quinquenio(self, edad, esperado):
        """
        Qué es: prueba unitaria de quinquenio_orden (posición numérica).
        Qué hace: calcula la posición de edades en los bordes de cada tramo (7 casos).
        Esperado: 0 para "0-4" hasta 17 para "85 o más".
        """
        # Arrange: edad parametrizada

        # Act: calcular
        orden = quinquenio_orden(edad)

        # Assert: posición esperada
        assert orden == esperado

    def test_el_orden_alfabetico_de_las_etiquetas_no_coincide_con_el_orden_por_edad(self):
        """
        Qué es: prueba de la razón de ser de quinquenio_orden (ordenar los quinquenios en Power BI).
        Qué hace: ordena las etiquetas por texto y por la columna de orden.
        Esperado: los dos órdenes difieren (alfabéticamente "5-9" va después de "40-44"); el de quinquenio_orden
                  empieza por "0-4" y termina en "85 o más", y cada etiqueta tiene una única posición.
        """
        # Arrange: pares (etiqueta, posición) de todas las edades del dominio
        pares = {(MAPEO_QUINQUENIOS[e], MAPEO_ORDEN[e]) for e in MAPEO_QUINQUENIOS}

        # Act: ordenar de las dos formas
        por_texto = sorted(etiqueta for etiqueta, _ in pares)
        por_posicion = [etiqueta for etiqueta, _ in sorted(pares, key=lambda par: par[1])]

        # Assert: distinto orden, extremos correctos y relación uno a uno
        assert por_texto != por_posicion
        assert (por_posicion[0], por_posicion[-1]) == ("0-4", "85 o más")
        assert len(pares) == len({etiqueta for etiqueta, _ in pares}) == 18


class TestEdadEnAniosCumplidos:
    def test_meses_se_dividen_entre_doce_y_anios_quedan_igual(self):
        """
        Qué es: prueba unitaria de edad_en_anios_cumplidos (conversión por unidad).
        Qué hace: convierte cinco edades sintéticas en años y en meses, con una edad y unidad nulas.
        Esperado: los años no cambian, los meses pasan a años cumplidos (11 meses = 0; 60 meses = 5) y el
                  nulo se conserva; el resultado es Int64.
        """
        # Arrange: edades y unidades sintéticas (sin datos reales)
        edad = pd.Series([34, 11, 60, 87, None], dtype="Int64")
        unidad = pd.Series(["Años", "Meses", "Meses", "Años", None])

        # Act: convertir
        anios = edad_en_anios_cumplidos(edad, unidad)

        # Assert: valores, nulo y tipo
        assert anios.iloc[:4].tolist() == [34, 0, 5, 87]
        assert pd.isna(anios.iloc[4])
        assert str(anios.dtype) == "Int64"

    def test_unidad_desconocida_detiene_la_ejecucion(self):
        """
        Qué es: prueba unitaria del contrato de la unidad de edad.
        Qué hace: incluye una unidad que no es 'Años' ni 'Meses'.
        Esperado: ValueError que menciona la unidad inesperada: el origen cambió y no se corrige en silencio.
        """
        # Arrange: una unidad inventada
        edad = pd.Series([3, 4], dtype="Int64")
        unidad = pd.Series(["Años", "Días"])

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="unidad_de_edad inesperada"):
            edad_en_anios_cumplidos(edad, unidad)

    def test_edad_sin_unidad_detiene_la_ejecucion(self):
        """
        Qué es: prueba unitaria del contrato "toda edad trae su unidad".
        Qué hace: deja una edad registrada sin unidad.
        Esperado: ValueError que cuenta las edades sin unidad.
        """
        # Arrange: una edad sin unidad
        edad = pd.Series([3, 4], dtype="Int64")
        unidad = pd.Series(["Años", None])

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="1 edades sin unidad_de_edad"):
            edad_en_anios_cumplidos(edad, unidad)


class TestDerivarQuinquenios:
    def test_agrega_las_dos_columnas_y_conserva_el_origen(self, reporte):
        """
        Qué es: prueba unitaria de derivar_quinquenios (caso normal).
        Qué hace: deriva los quinquenios de tres edades sintéticas, una nula.
        Esperado: aparecen quinquenio_edad y quinquenio_orden (Int64) con nulo donde no hay edad, la columna de
                  origen se conserva y la auditoría de las derivadas no tiene pérdidas sin explicar.
        """
        # Arrange: edades sintéticas ya validadas en [0, 120]
        df = pd.DataFrame({"edad": pd.array([34, 87, None], dtype="Int64")})

        # Act: derivar
        resultado = derivar_quinquenios(df, reporte, BLOQUE, df["edad"])

        # Assert: columnas, valores, tipo y auditoría
        assert list(resultado.columns) == ["edad", "quinquenio_edad", "quinquenio_orden"]
        assert resultado["quinquenio_edad"].iloc[:2].tolist() == ["30-34", "85 o más"]
        assert resultado["quinquenio_orden"].iloc[:2].tolist() == [6, 17]
        assert str(resultado["quinquenio_orden"].dtype) == "Int64"
        assert resultado[["quinquenio_edad", "quinquenio_orden"]].isna().iloc[2].all()
        reporte.verificar_auditoria()

    def test_con_edad_en_meses_usa_los_anios_cumplidos(self, reporte):
        """
        Qué es: prueba unitaria de derivar_quinquenios con años calculados aparte (caso del Excel, con unidad).
        Qué hace: pasa edades en meses (11 y 60) y deriva el quinquenio desde los años cumplidos.
        Esperado: 11 meses cae en "0-4" y 60 meses (5 años) en "5-9", aunque el número de la edad sea mayor.
        """
        # Arrange: edades y unidades sintéticas
        df = pd.DataFrame({"edad": pd.array([11, 60], dtype="Int64"), "unidad_de_edad": ["Meses", "Meses"]})
        anios = edad_en_anios_cumplidos(df["edad"], df["unidad_de_edad"])

        # Act: derivar desde los años cumplidos, no desde el valor crudo
        resultado = derivar_quinquenios(df, reporte, BLOQUE, anios)

        # Assert: el tramo sigue a los años cumplidos
        assert resultado["quinquenio_edad"].tolist() == ["0-4", "5-9"]
        assert resultado["quinquenio_orden"].tolist() == [0, 1]
        reporte.verificar_auditoria()
