"""
Lectura del staging de una fuente para la carga a la bodega.

Para validar solo se leen metadatos de cada Parquet (esquema y número de filas); para cargar, solo las
columnas que pide el contrato, nunca el staging completo (minimización de datos).
"""
import json
import os

import pandas as pd
import pyarrow.parquet as pq

NOMBRE_MANIFIESTO = "manifiesto.json"
CLAVES_MANIFIESTO = ("run_id", "source_type", "rows")


def leer_manifiesto(staging_dir: str) -> dict:
    """
    Lee el manifiesto del staging y comprueba que describe exactamente los Parquet de la carpeta.

    Args:
        staging_dir (str): carpeta del staging de una fuente (ej. "data/staging/redcap").

    Returns:
        dict: el manifiesto (`run_id`, `source_type`, `rows` por tabla, ...).

    Raises:
        FileNotFoundError: si no hay manifiesto (no hay staging, o es anterior a que el manifiesto se copiara
            al staging: hay que volver a ejecutar la transformación).
        ValueError: si le faltan claves, si falta o sobra una tabla o si el número de filas de un Parquet no
            coincide con el del manifiesto (la foto no es de una sola corrida).
    """
    ruta = os.path.join(staging_dir, NOMBRE_MANIFIESTO)
    if not os.path.isfile(ruta):
        raise FileNotFoundError(
            f"No hay manifiesto en '{staging_dir}'. Ejecute la transformación de la fuente antes de cargar."
        )
    with open(ruta, encoding="utf-8") as f:
        manifiesto = json.load(f)

    faltantes = [clave for clave in CLAVES_MANIFIESTO if clave not in manifiesto]
    if faltantes:
        raise ValueError(f"Al manifiesto de '{staging_dir}' le faltan las claves {faltantes}")

    presentes = {nombre[:-len(".parquet")] for nombre in os.listdir(staging_dir) if nombre.endswith(".parquet")}
    esperadas = set(manifiesto["rows"])
    if presentes != esperadas:
        raise ValueError(
            f"El staging de '{staging_dir}' no coincide con su manifiesto: "
            f"faltan {sorted(esperadas - presentes)}, sobran {sorted(presentes - esperadas)}"
        )
    distintas = {}
    for tabla, filas in manifiesto["rows"].items():
        observadas = pq.read_metadata(os.path.join(staging_dir, f"{tabla}.parquet")).num_rows
        if observadas != filas:
            distintas[tabla] = {"manifiesto": filas, "parquet": observadas}
    if distintas:
        raise ValueError(f"Las filas del manifiesto y de los Parquet no coinciden en '{staging_dir}': {distintas}")
    return manifiesto


def esquema_staging(staging_dir: str, tablas: list[str]) -> dict[str, dict[str, str]]:
    """
    Esquema de las tablas indicadas, leído de los metadatos de cada Parquet (sin leer filas).

    Returns:
        dict: {tabla: {columna: tipo de Arrow como texto}}. Una tabla sin Parquet no aparece, para que la
            validación del contrato la reporte junto con las columnas que faltan.
    """
    esquema = {}
    for tabla in tablas:
        ruta = os.path.join(staging_dir, f"{tabla}.parquet")
        if os.path.isfile(ruta):
            esquema[tabla] = {campo.name: str(campo.type) for campo in pq.read_schema(ruta)}
    return esquema


def leer_tablas(staging_dir: str, columnas: dict[str, list[str]]) -> dict[str, pd.DataFrame]:
    """
    Lee del staging solo las columnas pedidas de cada tabla.

    Args:
        columnas (dict): {tabla: [columnas]}, tal como lo devuelve `Contrato.columnas_por_tabla`.
    """
    return {
        tabla: pd.read_parquet(os.path.join(staging_dir, f"{tabla}.parquet"), columns=cols, engine="pyarrow")
        for tabla, cols in columnas.items()
    }
