"""
Cuarentena de la carga: filas que no pueden entrar a la bodega, guardadas en Parquet con la regla
que incumplieron, en data/quarantine/<modelo>/<fuente>/run_id=<id>/. Están fuera de la base, lejos del rol
de Power BI. Sin cuarentena habría que abortar la carga por una fila o descartarla en silencio.
"""
import os

import pandas as pd

COLUMNA_REGLA = "regla_cuarentena"


def escribir_cuarentena(cuarentena: dict[str, pd.DataFrame], base_dir: str, modelo: str, fuente: str,
                        run_id: str) -> str | None:
    """
    Escribe un Parquet por tabla de staging con filas en cuarentena.

    Returns:
        str | None: la carpeta escrita, o None si ninguna tabla tiene filas (no se crea una carpeta vacía).

    Raises:
        ValueError: si una tabla no indica la regla incumplida de cada fila (columna `regla_cuarentena`).
    """
    con_filas = {tabla: df for tabla, df in cuarentena.items() if not df.empty}
    if not con_filas:
        return None
    sin_regla = [tabla for tabla, df in con_filas.items()
                 if COLUMNA_REGLA not in df.columns or df[COLUMNA_REGLA].isna().any()]
    if sin_regla:
        raise ValueError(f"Filas en cuarentena sin '{COLUMNA_REGLA}' en las tablas {sin_regla}")

    carpeta = os.path.join(base_dir, modelo, fuente, f"run_id={run_id}")
    os.makedirs(carpeta, exist_ok=True)
    for tabla, df in con_filas.items():
        df.to_parquet(os.path.join(carpeta, f"{tabla}.parquet"), engine="pyarrow", compression="snappy", index=False)
    return carpeta
