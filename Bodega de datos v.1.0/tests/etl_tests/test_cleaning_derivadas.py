import pandas as pd

from etl.transform.common.cleaning import derivar_duracion_seg, formatear_hms, registrar_derivada


class TestDerivarDuracionSegundos:
    def test_calcula_segundos_enteros(self, reporte):
        """
        Qué es: prueba unitaria de derivar_duracion_seg (control positivo).
        Qué hace: calcula la duración entre dos fechas con 45 minutos de diferencia.
        Esperado: 2700 segundos, tipo Int64 y auditoría sin pérdidas.
        """
        # Arrange: inicio y fin sintéticos
        df = pd.DataFrame({"ini": pd.to_datetime(["2024-01-01 10:00"]),
                           "fin": pd.to_datetime(["2024-01-01 10:45"])})

        # Act: derivar
        derivar_duracion_seg(df, reporte, "demo", "ini", "fin", "dur_seg")

        # Assert: una sola columna, exacta y entera
        assert df["dur_seg"].tolist() == [2700]
        assert str(df["dur_seg"].dtype) == "Int64"
        assert reporte.auditoria[("demo", "dur_seg")]["conserva"] is True

    def test_duracion_negativa_se_invalida_y_se_cuenta(self, reporte):
        """
        Qué es: prueba unitaria de derivar_duracion_seg (fin anterior al inicio).
        Qué hace: calcula la duración cuando el fin es 30 minutos anterior al inicio.
        Esperado: la duración queda NA, fuera_de_rango = 1 (contado como debajo del mínimo) y la auditoría
                  conserva = True.
        """
        # Arrange: fechas contradictorias
        df = pd.DataFrame({"ini": pd.to_datetime(["2024-01-01 10:00"]),
                           "fin": pd.to_datetime(["2024-01-01 09:30"])})

        # Act: derivar
        derivar_duracion_seg(df, reporte, "demo", "ini", "fin", "dur_seg")

        # Assert: no se corrige ni se invierte; se invalida y se cuenta
        assert df["dur_seg"].isna().tolist() == [True]
        fila = reporte.auditoria[("demo", "dur_seg")]
        assert (fila["fuera_de_rango"], fila["conserva"]) == (1, True)
        assert (fila["bajo_minimo"], fila["sobre_maximo"]) == (1, 0)

    def test_falta_una_fecha_deja_na_sin_contar_perdida(self, reporte):
        """
        Qué es: prueba unitaria de derivar_duracion_seg (fecha ausente).
        Qué hace: calcula la duración cuando falta la fecha de fin.
        Esperado: la duración queda NA y no se cuenta como pérdida (no_nulos_antes = 0).
        """
        # Arrange: inicio presente y fin nulo
        df = pd.DataFrame({"ini": pd.to_datetime(["2024-01-01 10:00"]), "fin": pd.to_datetime([None])})

        # Act: derivar
        derivar_duracion_seg(df, reporte, "demo", "ini", "fin", "dur_seg")

        # Assert: sin ambas fechas no hay duración que perder
        fila = reporte.auditoria[("demo", "dur_seg")]
        assert df["dur_seg"].isna().tolist() == [True]
        assert (fila["no_nulos_antes"], fila["conserva"]) == (0, True)


class TestFormatearHms:
    def test_formatea_hh_mm_ss_y_horas_mayores_a_24(self):
        """
        Qué es: prueba unitaria de formatear_hms.
        Qué hace: formatea 2700, 3661 y 90000 segundos.
        Esperado: "00:45:00", "01:01:01" y "25:00:00" (las horas pueden superar 24).
        """
        # Arrange: segundos enteros (Int64), como los produce derivar_duracion_seg
        segundos = pd.Series([2700, 3661, 90000], dtype="Int64")

        # Act: formatear
        texto = formatear_hms(segundos)

        # Assert: el formato HH:MM:SS se genera solo para mostrar, sin almacenarlo
        assert texto.tolist() == ["00:45:00", "01:01:01", "25:00:00"]


class TestRegistrarDerivada:
    def test_derivada_completa_conserva(self, reporte):
        """
        Qué es: prueba unitaria de registrar_derivada (control positivo).
        Qué hace: audita una derivada que tiene valor para todos los valores de su origen.
        Esperado: conserva = True.
        """
        # Arrange: cada edad produjo su quinquenio
        df = pd.DataFrame({"edad": pd.array([10, 20], dtype="Int64"), "quinquenio": ["10-14", "20-24"]})

        # Act: registrar
        registrar_derivada(df, reporte, "demo", "edad", "quinquenio")

        # Assert: toda edad de origen produjo un valor derivado
        assert reporte.auditoria[("demo", "quinquenio")]["conserva"] is True

    def test_derivada_con_hueco_no_conserva(self, reporte):
        """
        Qué es: prueba unitaria de registrar_derivada (caso defectuoso).
        Qué hace: audita una derivada que quedó nula para un valor presente en el origen.
        Esperado: diferencia_sin_explicar = 1 y conserva = False.
        """
        # Arrange: una edad sin quinquenio (p. ej. fuera del diccionario de mapeo)
        df = pd.DataFrame({"edad": pd.array([10, 20], dtype="Int64"), "quinquenio": ["10-14", None]})

        # Act: registrar
        registrar_derivada(df, reporte, "demo", "edad", "quinquenio")

        # Assert: sin pérdidas explicadas, el hueco debe quedar visible
        fila = reporte.auditoria[("demo", "quinquenio")]
        assert (fila["diferencia_sin_explicar"], fila["conserva"]) == (1, False)
