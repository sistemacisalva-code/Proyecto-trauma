"""
Generadores de las dimensiones de tiempo: calendario y horario no salen del staging. Producen todos los
atributos posibles; el contrato de cada modelo elige los suyos, con su nombre y sus etiquetas. Como las
dimensiones están completas, una fecha u hora que no se encuentra es un error real y no se tapa creando la fila.

Los nombres de meses y días y la hora larga se escriben a mano en español: `strftime` depende del idioma del
sistema donde corre el pipeline.
"""
from datetime import date

import holidays
import pandas as pd

from etl.load.warehouse.contrato import ATRIBUTOS_GENERADOS

# Primer año de la ventana del Excel (decisión 3.6 del plan de Excel)
FECHA_INICIO = date(2011, 1, 1)
PAIS_FESTIVOS = "CO"   # el hospital está en Cali: festivos de Colombia, con los trasladados por la Ley 51 de 1983

NOMBRES_MES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre",
               "Octubre", "Noviembre", "Diciembre")
NOMBRES_DIA = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")   # ISO 8601: lunes = 1


def rango_calendario(hoy: date) -> tuple[date, date]:
    """Desde el inicio de la ventana del Excel hasta el 31 de diciembre del año siguiente al de la corrida."""
    return FECHA_INICIO, date(hoy.year + 1, 12, 31)


def generar_calendario(desde: date, hasta: date) -> pd.DataFrame:
    """
    Una fila por fecha, sin huecos, con todos los atributos de ATRIBUTOS_GENERADOS["calendario"]. `es_festivo` es
    booleano; cada contrato le pone sus etiquetas.

    Raises:
        ValueError: si el rango está invertido.
    """
    if desde > hasta:
        raise ValueError(f"Rango de calendario invertido: {desde} > {hasta}")
    fechas = pd.date_range(desde, hasta, freq="D")
    festivos = holidays.country_holidays(PAIS_FESTIVOS, years=range(desde.year, hasta.year + 1))
    calendario = pd.DataFrame({
        "fecha": fechas.date,
        "dia": fechas.day,
        "mes": fechas.month,
        "nombre_mes": [NOMBRES_MES[mes - 1] for mes in fechas.month],
        "trimestre": fechas.quarter,
        "anio": fechas.year,
        "dia_semana": [NOMBRES_DIA[dia] for dia in fechas.dayofweek],
        "dia_semana_numero": fechas.dayofweek + 1,
        "es_festivo": [fecha in festivos for fecha in fechas.date],
    })
    return calendario[list(ATRIBUTOS_GENERADOS["calendario"])]


def hora_larga(hora: int, minuto: int) -> str:
    """Formato de 12 horas de los tableros: '12:00:00 a. m.', '1:05:00 p. m.' (hora sin cero a la izquierda)."""
    return f"{hora % 12 or 12}:{minuto:02d}:00 {'a. m.' if hora < 12 else 'p. m.'}"


def generar_horario() -> pd.DataFrame:
    """
    Las 1 440 filas del horario, en orden (00:00 → 23:59), para que la clave sustituta quede cronológica y Power BI
    pueda ordenar `hora_larga` por ella. `intervalo` es la franja 'HH:00 - HH:00'; la última es '23:00 - 00:00'.
    """
    filas = [
        {"hora_larga": hora_larga(hora, minuto), "hora": hora, "minuto": minuto,
         "intervalo": f"{hora:02d}:00 - {(hora + 1) % 24:02d}:00"}
        for hora in range(24) for minuto in range(60)
    ]
    return pd.DataFrame(filas)[list(ATRIBUTOS_GENERADOS["horario"])]


def atributos_del_contrato(generado: pd.DataFrame, columnas: dict[str, dict]) -> pd.DataFrame:
    """
    Elige, renombra y etiqueta los atributos generados según las columnas de una tabla calendario u horario del
    contrato (`{columna destino: {"generado": atributo, "etiquetas"?: {"verdadero", "falso"}}}`), en su orden.
    """
    salida = {}
    for columna, definicion in columnas.items():
        valores = generado[definicion["generado"]]
        if "etiquetas" in definicion:
            etiquetas = definicion["etiquetas"]
            valores = valores.map({True: etiquetas["verdadero"], False: etiquetas["falso"]})
        salida[columna] = valores
    return pd.DataFrame(salida)
