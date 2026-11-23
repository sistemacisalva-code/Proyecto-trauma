"""Edad y quinquenios, compartidos por las transformaciones de REDCap y del Excel histórico.

La edad exacta es un cuasi-identificador: el modelo solo usa el quinquenio (decisión 2.15 de REDCap y 3.7 del
plan de Excel). Las etiquetas y su posición se definen aquí para que ambas fuentes produzcan el mismo dominio.
"""
import pandas as pd

from etl.transform.common.cleaning import registrar_derivada
from etl.transform.common.quality import ReporteCalidad

EDAD_MAXIMA = 120
TOPE_ULTIMO_QUINQUENIO = 85

# Unidades de edad aceptadas y su divisor para pasar a años cumplidos
DIVISOR_A_ANIOS = {"Años": 1, "Meses": 12}


def quinquenio(edad: int) -> str:
    """0-4, 5-9, ..., 80-84 y '85 o más'."""
    if edad >= TOPE_ULTIMO_QUINQUENIO:
        return f"{TOPE_ULTIMO_QUINQUENIO} o más"
    inicio = (edad // 5) * 5
    return f"{inicio}-{inicio + 4}"


def quinquenio_orden(edad: int) -> int:
    """Posición del quinquenio: 0 para '0-4', 1 para '5-9', ..., 17 para '85 o más'.

    El texto se ordena alfabéticamente ("5-9" quedaría después de "40-44"); esta columna numérica permite
    ordenar por ella en Power BI. Se carga en dim_paciente junto con la etiqueta.
    """
    return min(edad // 5, TOPE_ULTIMO_QUINQUENIO // 5)


MAPEO_QUINQUENIOS = {edad: quinquenio(edad) for edad in range(0, EDAD_MAXIMA + 1)}
MAPEO_ORDEN = {edad: quinquenio_orden(edad) for edad in range(0, EDAD_MAXIMA + 1)}


def edad_en_anios_cumplidos(edad: pd.Series, unidad: pd.Series) -> pd.Series:
    """Pasa la edad registrada a años cumplidos según su unidad ('Años' o 'Meses'), solo para ubicar el quinquenio.

    Falla si hay una unidad desconocida o una edad sin unidad: el origen cambió y no se corrige en silencio.
    """
    desconocidas = set(unidad.dropna().unique()) - set(DIVISOR_A_ANIOS)
    if desconocidas:
        raise ValueError(f"unidad_de_edad inesperada: {sorted(desconocidas)}")
    sin_unidad = int((edad.notna() & unidad.isna()).sum())
    if sin_unidad:
        raise ValueError(f"{sin_unidad} edades sin unidad_de_edad")
    return edad // unidad.map(DIVISOR_A_ANIOS).astype("Int64")


def derivar_quinquenios(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str,
                        anios_cumplidos: pd.Series, origen: str = "edad") -> pd.DataFrame:
    """Agrega `quinquenio_edad` y `quinquenio_orden` (Int64) y registra cada derivada contra `origen` en la auditoría.

    `anios_cumplidos` debe estar alineada con `df` y dentro de [0, EDAD_MAXIMA] (o nula). No elimina `origen`:
    va al final del instrumento porque la auditoría de la derivada la necesita.
    """
    df["quinquenio_edad"] = anios_cumplidos.map(MAPEO_QUINQUENIOS)
    registrar_derivada(df, reporte, bloque, origen, "quinquenio_edad")

    df["quinquenio_orden"] = anios_cumplidos.map(MAPEO_ORDEN).astype("Int64")
    registrar_derivada(df, reporte, bloque, origen, "quinquenio_orden")
    return df
