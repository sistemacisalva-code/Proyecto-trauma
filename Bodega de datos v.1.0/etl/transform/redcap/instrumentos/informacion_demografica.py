"""Instrumento informacion_demografica: grano episodio (una fila por record_id)."""
import pandas as pd

from etl.transform.common.cleaning import convertir_fecha, convertir_numerico
from etl.transform.common.demografia import EDAD_MAXIMA, derivar_quinquenios
from etl.transform.common.keys import validar_grano
from etl.transform.common.quality import ReporteCalidad

NOMBRE = "informacion_demografica"
# Categóricas cuyos valores únicos se listan en el perfil (solo si tienen <= CARDINALIDAD_MAXIMA)
CATEGORICAS = ("genero", "estado_civil", "pais", "nacionalidad", "paciente_asegurado",
               "tipo_de_seguro", "referido")
# El Excel marca el seguro sin informar con esta etiqueta; REDCap no tiene ninguna y lo deja vacío (2026-10-31)
SEGURO_SIN_INFORMAR = "No especificado"


def transformar(df: pd.DataFrame, reporte: ReporteCalidad, bloques: dict) -> pd.DataFrame:
    # Grano: instrumento no repetible, una fila por episodio
    validar_grano(df, ["record_id"], NOMBRE)

    # El export no trae segundos
    convertir_fecha(df, reporte, NOMBRE, "fecha_y_hora_de_llegada_del_paciente", "%Y-%m-%d %H:%M")

    # Contrato entero (un decimal detiene la ejecución) y dominio [0, 120] (invalida y reporta)
    convertir_numerico(df, reporte, NOMBRE, "edad", "Int64", entero=True, rango=(0, EDAD_MAXIMA))

    # REDCap no ofrece una opción para el seguro no informado, así que se adopta la etiqueta del Excel: el atributo queda
    # con un único dominio en la bodega y el vacío deja de significar dos cosas distintas según la fuente
    sin_informar = df["tipo_de_seguro"].isna()
    reporte.registrar_correccion(NOMBRE, "tipo_de_seguro",
                                 f"seguro vacio etiquetado como '{SEGURO_SIN_INFORMAR}' (dominio del Excel)",
                                 int(sin_informar.sum()), "completado")
    df["tipo_de_seguro"] = df["tipo_de_seguro"].fillna(SEGURO_SIN_INFORMAR)

    # En REDCap la edad siempre está en años
    derivar_quinquenios(df, reporte, NOMBRE, df["edad"])

    # Solo se usa el quinquenio: la edad exacta es redundante y es un cuasi-identificador.
    # Va al final porque la auditoría de la derivada la necesita.
    return df.drop(columns="edad")
