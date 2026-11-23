from datetime import date
from pathlib import Path

import pytest

from etl.load.warehouse.calendario import (
    atributos_del_contrato, generar_calendario, generar_horario, rango_calendario,
)
from etl.load.warehouse.contrato import ATRIBUTOS_GENERADOS, leer_contrato

CONTRATO_COMPLETO = Path(__file__).resolve().parents[2] / "config" / "contratos" / "completo.yaml"

# Festivos oficiales de Colombia en 2024 (calendario publicado): fijos, trasladados al lunes por la Ley 51 de 1983
# y los que dependen de la Semana Santa (Pascua: 31 de marzo)
FESTIVOS_2024 = {
    date(2024, 1, 1), date(2024, 1, 8), date(2024, 3, 25), date(2024, 3, 28), date(2024, 3, 29),
    date(2024, 5, 1), date(2024, 5, 13), date(2024, 6, 3), date(2024, 6, 10), date(2024, 7, 1),
    date(2024, 7, 20), date(2024, 8, 7), date(2024, 8, 19), date(2024, 10, 14), date(2024, 11, 4),
    date(2024, 11, 11), date(2024, 12, 8), date(2024, 12, 25),
}


class TestHorario:
    def test_genera_los_1440_minutos_en_orden(self):
        """
        Qué es: prueba unitaria de generar_horario.
        Qué hace: genera el horario completo.
        Esperado: 1 440 filas con los atributos de ATRIBUTOS_GENERADOS["horario"], sin parejas (hora, minuto)
                  repetidas y en orden cronológico (la clave sustituta se asigna en ese orden).
        """
        # Arrange: no aplica, el generador no recibe parámetros

        # Act
        horario = generar_horario()

        # Assert: completo, único y ordenado
        assert list(horario.columns) == list(ATRIBUTOS_GENERADOS["horario"])
        assert len(horario) == 1440
        assert not horario.duplicated(["hora", "minuto"]).any()
        minutos = horario["hora"] * 60 + horario["minuto"]
        assert minutos.tolist() == list(range(1440))

    @pytest.mark.parametrize("hora, minuto, larga, intervalo", [
        (0, 0, "12:00:00 a. m.", "00:00 - 01:00"),
        (11, 59, "11:59:00 a. m.", "11:00 - 12:00"),
        (12, 0, "12:00:00 p. m.", "12:00 - 13:00"),
        (13, 5, "1:05:00 p. m.", "13:00 - 14:00"),
        (23, 59, "11:59:00 p. m.", "23:00 - 00:00"),
    ])
    def test_etiquetas_de_los_bordes(self, hora, minuto, larga, intervalo):
        """
        Qué es: prueba unitaria de las etiquetas del horario.
        Qué hace: busca en el horario generado la medianoche, el fin de la mañana, el mediodía, una hora de la tarde
                  y el último minuto del día.
        Esperado: hora larga en 12 horas sin cero a la izquierda ('12:00:00 a. m.' a medianoche, '12:00:00 p. m.' a
                  mediodía) y la franja de su hora; la última franja es '23:00 - 00:00'.
        """
        # Arrange: horario completo
        horario = generar_horario().set_index(["hora", "minuto"])

        # Act: fila del minuto pedido
        fila = horario.loc[(hora, minuto)]

        # Assert: etiquetas del tablero
        assert fila["hora_larga"] == larga
        assert fila["intervalo"] == intervalo


class TestCalendario:
    def test_rango_va_del_inicio_del_excel_al_fin_del_anio_siguiente(self):
        """
        Qué es: prueba unitaria de rango_calendario.
        Qué hace: calcula el rango para una corrida del 26 de octubre de 2026.
        Esperado: del 1 de enero de 2011 (ventana del Excel) al 31 de diciembre de 2027.
        """
        # Arrange: fecha de la corrida
        hoy = date(2026, 10, 26)

        # Act
        rango = rango_calendario(hoy)

        # Assert
        assert rango == (date(2011, 1, 1), date(2027, 12, 31))

    def test_atributos_de_una_fecha_conocida(self):
        """
        Qué es: prueba unitaria de los atributos de generar_calendario.
        Qué hace: genera el año 2024 y toma el Viernes Santo (29 de marzo).
        Esperado: 366 filas sin huecos (año bisiesto); día 29, mes 3, 'Marzo', trimestre 1, año 2024, 'Viernes', día
                  de la semana 5 (lunes = 1) y festivo.
        """
        # Arrange: rango de un año bisiesto
        desde, hasta = date(2024, 1, 1), date(2024, 12, 31)

        # Act
        calendario = generar_calendario(desde, hasta)
        fila = calendario.set_index("fecha").loc[date(2024, 3, 29)]

        # Assert: forma y atributos
        assert list(calendario.columns) == list(ATRIBUTOS_GENERADOS["calendario"])
        assert len(calendario) == 366 and calendario["fecha"].is_unique
        assert (fila["dia"], fila["mes"], fila["nombre_mes"], fila["trimestre"], fila["anio"]) == (29, 3, "Marzo", 1, 2024)
        assert (fila["dia_semana"], fila["dia_semana_numero"], fila["es_festivo"]) == ("Viernes", 5, True)

    def test_festivos_de_colombia_2024(self):
        """
        Qué es: prueba unitaria de los festivos (librería holidays con la versión fijada en requirements.txt).
        Qué hace: genera 2024 y toma las fechas marcadas como festivas.
        Esperado: exactamente los 18 festivos oficiales de Colombia de 2024, incluidos los trasladados al lunes
                  (Reyes el 8 de enero, Asunción el 19 de agosto, etc.) y los de Semana Santa. Si una versión nueva
                  de la librería cambia algo, esta prueba lo detecta.
        """
        # Arrange: rango de 2024
        desde, hasta = date(2024, 1, 1), date(2024, 12, 31)

        # Act
        calendario = generar_calendario(desde, hasta)

        # Assert
        assert set(calendario.loc[calendario["es_festivo"], "fecha"]) == FESTIVOS_2024

    def test_rango_invertido_se_rechaza(self):
        """
        Qué es: prueba unitaria de la validación del rango de generar_calendario.
        Qué hace: pide un calendario cuyo inicio es posterior a su fin.
        Esperado: ValueError (no un calendario vacío, que haría fallar después todas las fechas).
        """
        # Arrange: rango invertido
        desde, hasta = date(2024, 12, 31), date(2024, 1, 1)

        # Act + Assert
        with pytest.raises(ValueError, match="invertido"):
            generar_calendario(desde, hasta)


class TestAtributosDelContrato:
    def test_dim_tiempo_del_completo(self):
        """
        Qué es: prueba unitaria de atributos_del_contrato con el contrato real del completo.
        Qué hace: aplica las columnas de dim_tiempo de completo.yaml a una semana generada.
        Esperado: las columnas del DDL en el orden del contrato, sin dia_semana_numero (el completo no lo usa), y
                  es_festivo con las etiquetas 'SI' / 'NO' del CHECK.
        """
        # Arrange: semana con un festivo (lunes 8 de enero de 2024, Reyes trasladado)
        columnas = leer_contrato(str(CONTRATO_COMPLETO), "completo").tablas["dim_tiempo"]["columnas"]
        semana = generar_calendario(date(2024, 1, 8), date(2024, 1, 14))

        # Act
        dim_tiempo = atributos_del_contrato(semana, columnas)

        # Assert
        assert list(dim_tiempo.columns) == list(columnas)
        assert "dia_semana_numero" not in dim_tiempo.columns
        assert dim_tiempo["es_festivo"].tolist() == ["SI", "NO", "NO", "NO", "NO", "NO", "NO"]

    def test_renombra_y_etiqueta_como_el_mini(self):
        """
        Qué es: prueba unitaria de atributos_del_contrato con columnas al estilo del mini (sintéticas).
        Qué hace: pide diames <- dia, dayofweeknumber <- dia_semana_numero y es_festivo con etiquetas 'True'/'False'.
        Esperado: los nombres del mini con los valores del generador; un mismo generador sirve a los dos modelos.
        """
        # Arrange: columnas del calendario del mini y un día festivo
        columnas = {
            "diames": {"generado": "dia"},
            "dayofweeknumber": {"generado": "dia_semana_numero"},
            "es_festivo": {"generado": "es_festivo", "etiquetas": {"verdadero": "True", "falso": "False"}},
        }
        dia = generar_calendario(date(2024, 12, 25), date(2024, 12, 25))

        # Act
        calendario = atributos_del_contrato(dia, columnas)

        # Assert: miércoles 25 de diciembre
        assert calendario.iloc[0].tolist() == [25, 3, "True"]
