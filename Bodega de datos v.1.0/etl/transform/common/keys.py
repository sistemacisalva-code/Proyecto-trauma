"""Llaves naturales de la capa de transformación: namespacing por fuente (ver decisiones_llaves_transform.md).

`trauma_register_id` (llave natural del hecho) se deriva de `source_system` y la llave original de la
fuente, que se conserva sin modificar en `source_record_id`. El surrogate `fact_id` se genera al cargar.
"""
import pandas as pd

from etl.transform.common.quality import ReporteCalidad

COL_TRAUMA = "trauma_register_id"
COL_ORIGEN = "source_record_id"
COL_SISTEMA = "source_system"

# El prefijo es una garantía estructural de unicidad entre fuentes; vive aquí y en ningún otro lugar
PREFIJOS_FUENTE = {"redcap": "RC", "excel_historico": "EX"}


def validar_grano(df: pd.DataFrame, columnas: list[str], nombre: str) -> None:
    """Detiene la ejecución si la clave se repite o es nula: el grano debe ser único y verificable."""
    if df[columnas].isna().any().any():
        raise ValueError(f"{nombre}: hay valores nulos en la clave {columnas}")
    if df.duplicated(subset=columnas).any():
        raise ValueError(f"{nombre}: la clave {columnas} no es única")


def construir_trauma_register_id(source_system: str, ids: pd.Series) -> pd.Series:
    """f"{prefijo}-{id}" (por ejemplo 'RC-123'); el id original no se modifica.

    Raises:
        ValueError: fuente desconocida o ids nulos/vacíos.
    """
    prefijo = PREFIJOS_FUENTE.get(source_system)
    if prefijo is None:
        raise ValueError(f"Fuente sin prefijo de llave: '{source_system}'. Disponibles: {list(PREFIJOS_FUENTE)}")
    texto = ids.astype("string")
    if texto.isna().any() or (texto.str.len() == 0).any():
        raise ValueError("Hay identificadores de registro nulos o vacíos")
    return prefijo + "-" + texto


def aplicar_llaves(tablas: dict[str, pd.DataFrame], source_system: str, tabla_base: str,
                   reporte: ReporteCalidad, col_id: str = "record_id") -> dict[str, pd.DataFrame]:
    """Reemplaza `col_id` por las llaves del esquema canónico en todas las tablas.

    - tabla base (grano episodio): trauma_register_id, source_record_id y source_system. El id original
      se renombra, no se copia, para no duplicar la columna.
    - tablas hijas: solo trauma_register_id, que es la llave natural hacia el hecho.
    Las filas hijas sin episodio en la tabla base no se eliminan: se cuentan como regla de consistencia.
    """
    if tabla_base not in tablas:
        raise KeyError(f"La tabla base '{tabla_base}' no está en la salida del transformer")
    validar_grano(tablas[tabla_base], [col_id], tabla_base)
    episodios = set(construir_trauma_register_id(source_system, tablas[tabla_base][col_id]))

    salida = {}
    for nombre, df in tablas.items():
        trauma = construir_trauma_register_id(source_system, df[col_id])
        original = df[col_id]
        df = df.drop(columns=col_id)
        if nombre == tabla_base:
            df.insert(0, COL_TRAUMA, trauma)
            df.insert(1, COL_ORIGEN, original)
            df.insert(2, COL_SISTEMA, source_system)
        else:
            df.insert(0, COL_TRAUMA, trauma)
            reporte.reportar_regla(nombre, f"filas sin episodio en la tabla base ({tabla_base})",
                                   pd.Series(True, index=df.index), ~trauma.isin(episodios), trauma, ["llave del registro"])
        salida[nombre] = df
    return salida
