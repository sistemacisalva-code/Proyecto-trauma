import json
import os
import shutil
from datetime import datetime

from etl.transform.common.reporte_clinico import construir_para_correccion
from etl.transform.common.reporte_md import construir_markdown

NOMBRES_REPORTE = (
    "auditoria", "reglas", "correcciones", "renombres", "exclusiones", "perfiles", "duplicados",
    "resumen_duplicados", "consolidacion", "resumen_bloques", "descartes", "balance_filas", "atenciones_descartadas",
    "detalle_filas",
)


def run_id_de(result) -> str:
    """Identificador de corrida a partir de `result.transformed_at` (UTC), con el mismo formato
    sin ":" de las particiones de raw (`%Y-%m-%dT%H%M%S`)."""
    return datetime.fromisoformat(result.transformed_at).strftime("%Y-%m-%dT%H%M%S")


def _escribir_manifiesto(manifiesto: dict, carpeta: str) -> None:
    with open(os.path.join(carpeta, "manifiesto.json"), "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)


def _reemplazar_directorio(nuevo: str, destino: str) -> None:
    """Sustituye `destino` por `nuevo` conservando el anterior hasta que el cambio termina.

    Si el reemplazo falla se restaura el contenido previo, de modo que el staging nunca queda
    a medias (os.replace sobre un directorio existente no es posible en Windows, por eso el
    respaldo intermedio).
    """
    respaldo = destino + ".old"
    if os.path.exists(respaldo):
        shutil.rmtree(respaldo)
    if os.path.exists(destino):
        os.replace(destino, respaldo)
    try:
        os.replace(nuevo, destino)
    except Exception:
        if os.path.exists(respaldo):
            os.replace(respaldo, destino)
        raise
    shutil.rmtree(respaldo, ignore_errors=True)


def save_transform_result(result, staging_dir: str, reports_dir: str) -> dict[str, str]:
    """
    Persiste el TransformResult: las tablas en staging (foto completa, se sobrescribe) y el
    reporte de calidad en una carpeta propia por corrida (historial, nunca se sobrescribe).

    Args:
        result: TransformResult retornado por BaseTransformer.run().
        staging_dir (str): carpeta del origen en staging (ej. "data/staging/redcap"); queda con
            un Parquet por tabla, `<tabla>.parquet`, y `manifiesto.json`.
        reports_dir (str): carpeta raíz de reportes (ej. "data/quality_reports"); se escribe en
            "{reports_dir}/{source_type}/run_id={run_id}/".

    Returns:
        dict: rutas escritas: {"staging": ..., "reporte": ...}.

    Orden: primero el reporte (solo agrega) y después el staging, para que un fallo al escribir
    el reporte no deje el staging reemplazado sin su trazabilidad. Las tablas se escriben en un
    directorio temporal y solo se intercambian si todas se escribieron bien.

    El mismo manifiesto se copia dentro del staging: viaja con las tablas en el mismo intercambio,
    así la carga a la bodega sabe de qué corrida es la foto que lee (`run_id`) sin buscarla entre
    los reportes.
    """
    run_id = run_id_de(result)
    manifiesto = {
        "run_id": run_id, "source_type": result.source_type,
        "transformed_at": result.transformed_at, "elapsed_seconds": result.elapsed_seconds,
        "rows": result.rows, "procedencia": getattr(result, "procedencia", {}),
    }

    # Reporte: una carpeta por corrida; las tablas vacías (p. ej. sin duplicados) no se escriben
    carpeta_reporte = os.path.join(reports_dir, result.source_type, f"run_id={run_id}")
    os.makedirs(carpeta_reporte, exist_ok=True)
    for nombre in NOMBRES_REPORTE:
        tabla = result.reporte.tabla(nombre)
        if not tabla.empty:
            tabla.to_parquet(os.path.join(carpeta_reporte, f"{nombre}.parquet"),
                             engine="pyarrow", compression="snappy", index=False)
    # Vista legible y compartible del reporte: solo conteos y nombres, sin llaves de registros
    with open(os.path.join(carpeta_reporte, "reporte.md"), "w", encoding="utf-8") as f:
        f.write(construir_markdown(result.reporte, result.source_type, run_id, result.transformed_at, result.rows))
    # Reporte para quien corrige: trae llaves de registros (sin valores) y es confidencial; solo si hay casos
    markdown, para_correccion = construir_para_correccion(result.reporte, result.source_type, run_id)
    if not para_correccion.empty:
        with open(os.path.join(carpeta_reporte, "para_correccion.md"), "w", encoding="utf-8") as f:
            f.write(markdown)
        para_correccion.to_csv(os.path.join(carpeta_reporte, "para_correccion.csv"), sep=";", index=False,
                               encoding="utf-8-sig")
    _escribir_manifiesto(manifiesto, carpeta_reporte)

    # Staging: escritura completa en un directorio temporal y cambio al final
    temporal = staging_dir + ".tmp"
    if os.path.exists(temporal):
        shutil.rmtree(temporal)
    os.makedirs(temporal)
    try:
        for nombre, df in result.tables.items():
            df.to_parquet(os.path.join(temporal, f"{nombre}.parquet"),
                          engine="pyarrow", compression="snappy", index=False)
        _escribir_manifiesto(manifiesto, temporal)
        os.makedirs(os.path.dirname(staging_dir) or ".", exist_ok=True)
        _reemplazar_directorio(temporal, staging_dir)
    except Exception:
        shutil.rmtree(temporal, ignore_errors=True)
        raise

    return {"staging": staging_dir, "reporte": carpeta_reporte}
