from datetime import datetime
import os


def save_extraction_result(result, dest_name: str, base_dir: str, load_date: str = None) -> str:
    """
    Persiste el DataFrame de un ExtractionResult como archivo Parquet,
    particionado por fecha de carga dentro de `base_dir`.

    Args:
        result: ExtractionResult (o cualquier objeto con atributo `.data: pd.DataFrame`)
            retornado por BaseExtractor.run().
        dest_name (str): nombre lógico del dataset de salida (ej. "registro_trauma"),
            usualmente el campo "dest" de la configuración de hojas en settings.py.
        base_dir (str): carpeta raíz donde se escribe el archivo (ej. "data/raw/excel_trauma").
        load_date (str, opcional): fecha de partición en formato "YYYY-MM-DD".
            Si no se especifica, se usa la fecha actual.

    Returns:
        str: ruta completa del archivo .parquet escrito, con la forma
            "{base_dir}/load_date={load_date}/{dest_name}.parquet".
    """
    load_date = load_date or datetime.now().strftime("%Y-%m-%d")
    carpeta = os.path.join(base_dir, f"load_date={load_date}")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, f"{dest_name}.parquet")
    result.data.to_parquet(ruta, engine="pyarrow", compression="snappy", index=False)
    return ruta
