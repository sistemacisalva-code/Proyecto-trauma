import pandas as pd
import pytest

from etl.transform.common.cleaning import (
    convertir_duracion,
    convertir_fecha,
    convertir_numerico,
    convertir_resultado_binario,
    registrar_estandarizacion,
)


class TestConvertirNumerico:
    def test_convierte_texto_a_entero_y_audita(self, reporte):
        """
        Qué es: prueba unitaria de convertir_numerico (control positivo).
        Qué hace: convierte una columna de texto con 2 valores y un nulo a Int64 con contrato entero.
        Esperado: tipo Int64, valores 34 y 58, nulo conservado y auditoría sin pérdidas.
        """
        # Arrange: texto numérico, como lo entrega el export en modo "label"
        df = pd.DataFrame({"edad": ["34", "58", None]})

        # Act: convertir
        convertir_numerico(df, reporte, "demo", "edad", "Int64", entero=True, rango=(0, 120))

        # Assert: tipo del modelo, datos intactos y conservación demostrada
        assert str(df["edad"].dtype) == "Int64"
        assert df["edad"].tolist()[:2] == [34, 58]
        assert df["edad"].isna().tolist() == [False, False, True]
        fila = reporte.auditoria[("demo", "edad")]
        assert (fila["conserva"], fila["no_convertibles"], fila["fuera_de_rango"]) == (True, 0, 0)

    def test_texto_no_numerico_se_cuenta_como_no_convertible(self, reporte):
        """
        Qué es: prueba unitaria de convertir_numerico (valor que no se puede convertir).
        Qué hace: convierte una columna donde 1 de 4 valores es texto no numérico.
        Esperado: ese valor queda nulo, no_convertibles = 1 y la auditoría conserva = True.
        """
        # Arrange: 25 % no convertible, por debajo del umbral de la guarda
        df = pd.DataFrame({"x": ["1", "2", "3", "texto"]})

        # Act: convertir
        convertir_numerico(df, reporte, "demo", "x")

        # Assert: la pérdida es explicada y cuantificada
        assert df["x"].isna().tolist() == [False, False, False, True]
        fila = reporte.auditoria[("demo", "x")]
        assert (fila["no_convertibles"], fila["conserva"]) == (1, True)

    def test_fuera_de_rango_se_invalida_y_se_cuenta(self, reporte):
        """
        Qué es: prueba unitaria de convertir_numerico (validación de dominio).
        Qué hace: convierte [10, 200, 30] con rango (0, 120).
        Esperado: el 200 queda nulo, fuera_de_rango = 1 y no_nulos_despues = 2.
        """
        # Arrange: un valor fuera del dominio válido
        df = pd.DataFrame({"x": ["10", "200", "30"]})

        # Act: convertir con rango
        convertir_numerico(df, reporte, "demo", "x", "Int64", entero=True, rango=(0, 120))

        # Assert: el valor atípico se invalida y se reporta, no se corrige
        assert df["x"].isna().tolist() == [False, True, False]
        fila = reporte.auditoria[("demo", "x")]
        assert (fila["fuera_de_rango"], fila["no_nulos_despues"], fila["conserva"]) == (1, 2, True)

    def test_desglosa_fuera_de_rango_en_debajo_del_minimo_y_encima_del_maximo(self, reporte):
        """
        Qué es: prueba unitaria del desglose de fuera_de_rango en convertir_numerico.
        Qué hace: convierte [-5, 10, 200, 300] con rango (0, 120).
        Esperado: bajo_minimo = 1 (el -5) y sobre_maximo = 2 (200 y 300), que suman fuera_de_rango = 3; el
                  desglose distingue un error de unidad (todos por encima) de uno de captura.
        """
        # Arrange: un valor por debajo del mínimo y dos por encima del máximo
        df = pd.DataFrame({"x": ["-5", "10", "200", "300"]})

        # Act: convertir con rango
        convertir_numerico(df, reporte, "demo", "x", "Float64", rango=(0, 120))

        # Assert: el desglose suma el total
        fila = reporte.auditoria[("demo", "x")]
        assert (fila["bajo_minimo"], fila["sobre_maximo"], fila["fuera_de_rango"]) == (1, 2, 3)

    def test_rango_sin_tope_superior_solo_invalida_el_minimo(self, reporte):
        """
        Qué es: prueba unitaria de convertir_numerico (rango abierto, como en días de hospitalización).
        Qué hace: convierte [-1, 5, 400] con rango (0, inf).
        Esperado: solo el -1 queda nulo; 5 y 400 se conservan.
        """
        # Arrange: un negativo y un valor grande pero legítimo
        df = pd.DataFrame({"dias": ["-1", "5", "400"]})

        # Act: convertir con mínimo 0 y sin máximo
        convertir_numerico(df, reporte, "demo", "dias", "Int64", entero=True, rango=(0, float("inf")))

        # Assert: una estancia larga es legítima; un valor negativo no
        assert df["dias"].isna().tolist() == [True, False, False]

    def test_decimal_en_columna_entera_lanza_valueerror(self, reporte):
        """
        Qué es: prueba unitaria del contrato entero de convertir_numerico.
        Qué hace: convierte una columna con un valor decimal exigiendo enteros.
        Esperado: lanza ValueError (el origen cambió).
        """
        # Arrange: un decimal en una columna que el modelo define como entera
        df = pd.DataFrame({"x": ["1.5", "2"]})

        # Act + Assert: no se trunca ni se redondea: se detiene
        with pytest.raises(ValueError):
            convertir_numerico(df, reporte, "demo", "x", "Int64", entero=True)

    def test_decimal_autorizado_se_invalida_y_se_cuenta(self, reporte, regla):
        """
        Qué es: prueba unitaria de invalidar_no_enteros en convertir_numerico.
        Qué hace: convierte a Int64 una columna sintética con un decimal, un entero y un nulo, autorizando invalidar.
        Esperado: no se detiene; el decimal queda NA, la regla registra 2 evaluables y 1 incumple, y la auditoría lo
                  cuenta como no convertible, sin diferencia sin explicar.
        """
        # Arrange: un decimal en una columna entera autorizada a invalidar
        df = pd.DataFrame({"x": ["18.5", "20", None]})

        # Act
        convertir_numerico(df, reporte, "demo", "x", "Int64", entero=True, invalidar_no_enteros=True)

        # Assert: valor invalidado, regla y auditoría cuadran
        assert df["x"].isna().tolist() == [True, False, True]
        assert str(df["x"].dtype) == "Int64"
        assert regla("demo", "x con decimal (invalidado)") == (2, 1)
        assert reporte.auditoria[("demo", "x")]["no_convertibles"] == 1
        reporte.verificar_auditoria()

    def test_tasa_de_no_convertibles_excedida_detiene_sin_modificar(self, reporte):
        """
        Qué es: prueba unitaria de la guarda verificar_tasa_no_convertibles (vía convertir_numerico).
        Qué hace: convierte una columna donde 3 de 4 valores (75 %) no son numéricos.
        Esperado: lanza ValueError antes de asignar; la columna queda igual y no se registra auditoría.
        """
        # Arrange: la mayoría no convertible, señal de un tipo o formato equivocado
        df = pd.DataFrame({"x": ["a", "b", "c", "1"]})

        # Act + Assert: se detiene antes de anular la columna
        with pytest.raises(ValueError):
            convertir_numerico(df, reporte, "demo", "x")
        assert df["x"].tolist() == ["a", "b", "c", "1"]
        assert reporte.auditoria == {}

    def test_conserva_el_indice_propio_sin_desplazar_valores(self, reporte):
        """
        Qué es: prueba unitaria de la regla de alineación por índice (decisión 2.9).
        Qué hace: convierte una columna de un DataFrame con índice no consecutivo [10, 11, 12].
        Esperado: los valores quedan en la fila correcta y el índice no cambia.
        """
        # Arrange: bloque con índice distinto de 0..n-1
        df = pd.DataFrame({"x": ["1", "2", "3"]}, index=[10, 11, 12])

        # Act: convertir
        convertir_numerico(df, reporte, "demo", "x")

        # Assert: la conversión usa la columna del propio bloque, por lo que no hay desplazamiento
        assert df["x"].tolist() == [1.0, 2.0, 3.0]
        assert list(df.index) == [10, 11, 12]


class TestConvertirFecha:
    def test_convierte_con_formato_explicito(self, reporte):
        """
        Qué es: prueba unitaria de convertir_fecha (control positivo).
        Qué hace: convierte una fecha-hora en texto con formato "%Y-%m-%d %H:%M" y un nulo.
        Esperado: la columna queda datetime con el valor correcto y el nulo se conserva.
        """
        # Arrange: el export trae minutos, sin segundos
        df = pd.DataFrame({"f": ["2024-06-23 23:09", None]})

        # Act: convertir
        convertir_fecha(df, reporte, "demo", "f", "%Y-%m-%d %H:%M")

        # Assert: tipo datetime, valor exacto y conservación
        assert pd.api.types.is_datetime64_any_dtype(df["f"])
        assert df["f"].iloc[0] == pd.Timestamp("2024-06-23 23:09")
        assert reporte.auditoria[("demo", "f")]["conserva"] is True

    def test_formato_equivocado_detiene_la_ejecucion(self, reporte):
        """
        Qué es: prueba unitaria de la guarda de no convertibles en convertir_fecha.
        Qué hace: convierte fechas con segundos usando un formato sin segundos.
        Esperado: lanza ValueError en lugar de anular la columna completa sin aviso.
        """
        # Arrange: el formato declarado no coincide con el valor (caso real de fecha_y_hora_de_alta)
        df = pd.DataFrame({"f": ["2024-06-23 23:09:00"] * 3})

        # Act + Assert: sin la guarda, la auditoría explicaría todo como "no convertible" y pasaría
        with pytest.raises(ValueError):
            convertir_fecha(df, reporte, "demo", "f", "%Y-%m-%d %H:%M")

    def test_valor_no_fecha_se_cuenta_como_no_convertible(self, reporte):
        """
        Qué es: prueba unitaria de convertir_fecha (valor aislado inválido).
        Qué hace: convierte una columna donde 1 de 4 valores no es una fecha.
        Esperado: ese valor queda NaT y no_convertibles = 1.
        """
        # Arrange: 25 % no convertible
        df = pd.DataFrame({"f": ["2024-06-23 23:09", "2024-06-24 10:00", "2024-06-25 08:30", "basura"]})

        # Act: convertir
        convertir_fecha(df, reporte, "demo", "f", "%Y-%m-%d %H:%M")

        # Assert: error de captura aislado: se cuenta, no detiene
        assert df["f"].isna().tolist() == [False, False, False, True]
        assert reporte.auditoria[("demo", "f")]["no_convertibles"] == 1


class TestConvertirDuracion:
    def test_convierte_hhmmss_a_minutos(self, reporte):
        """
        Qué es: prueba unitaria de convertir_duracion (control positivo).
        Qué hace: convierte "01:00:00", "00:15:00" y "00:00:30" a minutos.
        Esperado: 60, 15 y 0.5 (los segundos se conservan como fracción de minuto), tipo Float64.
        """
        # Arrange: duraciones en texto HH:MM:SS
        df = pd.DataFrame({"d": ["01:00:00", "00:15:00", "00:00:30"]})

        # Act: convertir
        convertir_duracion(df, reporte, "demo", "d")

        # Assert: unidad única (minutos) y sin pérdida de segundos
        assert df["d"].tolist() == [60.0, 15.0, 0.5]
        assert str(df["d"].dtype) == "Float64"

    def test_duracion_fuera_de_rango_se_invalida(self, reporte):
        """
        Qué es: prueba unitaria de convertir_duracion (validación de dominio).
        Qué hace: convierte "01:00:00" y "30:00:00" con un máximo de 1440 minutos.
        Esperado: la de 30 h queda nula y fuera_de_rango = 1, desglosado como encima del máximo.
        """
        # Arrange: una duración dentro del límite y otra por encima de 24 h
        df = pd.DataFrame({"d": ["01:00:00", "30:00:00"]})

        # Act: convertir con rango
        convertir_duracion(df, reporte, "demo", "d", rango_minutos=(0, 1440))

        # Assert: el valor fuera de dominio se invalida y se cuenta, con su extremo
        assert df["d"].isna().tolist() == [False, True]
        fila = reporte.auditoria[("demo", "d")]
        assert (fila["fuera_de_rango"], fila["bajo_minimo"], fila["sobre_maximo"]) == (1, 0, 1)

    def test_texto_no_duracion_se_cuenta_como_no_convertible(self, reporte):
        """
        Qué es: prueba unitaria de convertir_duracion (valor que no es una duración).
        Qué hace: convierte una columna donde 1 de 4 valores no es una duración.
        Esperado: ese valor queda nulo y no_convertibles = 1.
        """
        # Arrange: 25 % no convertible
        df = pd.DataFrame({"d": ["01:00:00", "02:00:00", "03:00:00", "abc"]})

        # Act: convertir
        convertir_duracion(df, reporte, "demo", "d")

        # Assert: queda cuantificado en la auditoría
        assert reporte.auditoria[("demo", "d")]["no_convertibles"] == 1


class TestConvertirResultadoBinario:
    def test_positivo_negativo_a_boolean_nullable(self, reporte):
        """
        Qué es: prueba unitaria de convertir_resultado_binario (control positivo).
        Qué hace: convierte POSITIVO, NEGATIVO y un nulo a boolean.
        Esperado: True, False y NA; el tipo es "boolean".
        """
        # Arrange: resultado de una prueba toxicológica sintética
        df = pd.DataFrame({"r": ["POSITIVO", "NEGATIVO", None]})

        # Act: convertir
        convertir_resultado_binario(df, reporte, "demo", "r")

        # Assert: la celda vacía NO se imputa como negativa (no se registró el examen)
        assert str(df["r"].dtype) == "boolean"
        assert df["r"].tolist()[:2] == [True, False]
        assert df["r"].isna().tolist() == [False, False, True]

    def test_valor_fuera_de_dominio_queda_na_y_se_cuenta(self, reporte):
        """
        Qué es: prueba unitaria de convertir_resultado_binario (dominio cerrado).
        Qué hace: convierte una columna donde 1 de 5 valores no es POSITIVO ni NEGATIVO.
        Esperado: ese valor queda NA y no_convertibles = 1.
        """
        # Arrange: un valor ajeno al dominio cerrado
        df = pd.DataFrame({"r": ["POSITIVO", "NEGATIVO", "NEGATIVO", "POSITIVO", "OTRO"]})

        # Act: convertir
        convertir_resultado_binario(df, reporte, "demo", "r")

        # Assert: cualquier desviación del dominio se detecta y se cuantifica
        assert df["r"].isna().tolist() == [False, False, False, False, True]
        assert reporte.auditoria[("demo", "r")]["no_convertibles"] == 1


class TestRegistrarEstandarizacion:
    def test_estandarizacion_completa_conserva(self, reporte):
        """
        Qué es: prueba unitaria de registrar_estandarizacion (control positivo).
        Qué hace: audita una recodificación donde todo valor informado encuentra su valor oficial y un nulo sigue nulo.
        Esperado: 0 no convertibles y auditoría que conserva (antes == después).
        """
        # Arrange: texto libre y su versión estandarizada, sin pérdidas
        original = pd.Series(["cali", "Santiago de Cali", None])
        resultado = pd.Series(["CALI", "CALI", None])

        # Act: auditar
        no_convertibles = registrar_estandarizacion(reporte, "bloque", "municipio", original, resultado)

        # Assert: nada se pierde
        fila = reporte.tabla("auditoria").iloc[0]
        assert no_convertibles == 0
        assert (fila["no_nulos_antes"], fila["no_nulos_despues"], fila["no_convertibles"]) == (2, 2, 0)
        assert bool(fila["conserva"])

    def test_valor_fuera_del_catalogo_cuenta_como_no_convertible(self, reporte):
        """
        Qué es: prueba unitaria de registrar_estandarizacion (control negativo explicado).
        Qué hace: audita una recodificación donde un valor informado no está en el catálogo y queda vacío.
        Esperado: se cuenta como no convertible, la diferencia sin explicar es 0 y la auditoría conserva.
        """
        # Arrange: tres valores informados, uno queda vacío por no pertenecer al dominio
        original = pd.Series(["cali", "otro pais", "palmira"])
        resultado = pd.Series(["CALI", None, "PALMIRA"])

        # Act
        no_convertibles = registrar_estandarizacion(reporte, "bloque", "municipio", original, resultado)

        # Assert: la pérdida queda explicada
        fila = reporte.tabla("auditoria").iloc[0]
        assert no_convertibles == 1
        assert (fila["no_nulos_antes"], fila["no_nulos_despues"], fila["diferencia_sin_explicar"]) == (3, 2, 0)
        assert bool(fila["conserva"])

    def test_original_consolidado_de_varias_columnas_y_auditoria_duplicada(self, reporte):
        """
        Qué es: prueba unitaria de registrar_estandarizacion con un original construido desde dos columnas.
        Qué hace: audita la columna consolidada (ciudad rellenada con cantón) y luego intenta auditarla otra vez.
        Esperado: la primera auditoría usa el original consolidado (2 informados); la segunda lanza ValueError.
        """
        # Arrange: ciudad vacía en una fila, rellenada desde el cantón
        ciudad = pd.Series(["cali", None, None])
        canton = pd.Series([None, "palmira", None])
        consolidado = ciudad.fillna(canton)
        resultado = pd.Series(["CALI", "PALMIRA", None])

        # Act: primera auditoría
        registrar_estandarizacion(reporte, "bloque", "municipio", consolidado, resultado)

        # Assert: conteo del consolidado y rechazo de la auditoría repetida
        assert reporte.tabla("auditoria").iloc[0]["no_nulos_antes"] == 2
        with pytest.raises(ValueError, match="ya fue auditada"):
            registrar_estandarizacion(reporte, "bloque", "municipio", consolidado, resultado)
