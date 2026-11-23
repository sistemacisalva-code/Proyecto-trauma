"""Unifica las particiones incrementales de la capa raw en una foto actual del proyecto REDCap."""
from pathlib import Path

import pandas as pd

ID = "record_id"
_PARTICION = "_particion"


def leer_particiones(raw_dir: str | Path, dest: str) -> dict[str, pd.DataFrame]:
    """Lee `<raw_dir>/load_date=<partición>/<dest>.parquet` de cada partición existente.

    Returns:
        {nombre de la partición (sin el prefijo 'load_date='): DataFrame}; vacío si no hay ninguna.
    """
    particiones = {}
    for carpeta in sorted(Path(raw_dir).glob("load_date=*")):
        archivo = carpeta / f"{dest}.parquet"
        if archivo.exists():
            particiones[carpeta.name.removeprefix("load_date=")] = pd.read_parquet(archivo)
    return particiones


def fecha_de_particion(nombre: str) -> pd.Timestamp | None:
    """Momento de extracción codificado en el nombre de la partición (%Y-%m-%dT%H%M%S); None si no coincide."""
    try:
        return pd.to_datetime(nombre, format="%Y-%m-%dT%H%M%S")
    except ValueError:
        return None


def consolidar_particiones(particiones: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Une las particiones `load_date=...` y conserva cada registro completo desde la más reciente que lo contiene.

    Supuesto confirmado: el export incremental de REDCap devuelve el registro completo (todas sus filas),
    no solo las instancias modificadas; por eso se reemplaza por record_id y no por fila. Esto también
    elimina las instancias borradas dentro de un registro modificado.
    Limitación: un registro eliminado por completo en REDCap no llega en ninguna extracción incremental
    (solo traen lo modificado) y permanece en la foto desde su partición antigua. Falta decidir cómo
    detectarlo (p. ej. comparar con una extracción completa periódica) y si se marca, se excluye o se conserva.

    Args:
        particiones: {nombre de la partición (load_date=...): DataFrame leído de su Parquet}.

    Returns:
        (foto consolidada, resumen de conteos).

    Raises:
        ValueError: sin particiones, todas vacías, esquema distinto entre particiones o record_id nulo.
    """
    if not particiones:
        raise ValueError("No hay particiones para consolidar")

    # El nombre de la carpeta (%Y-%m-%dT%H%M%S) ordena cronológicamente como texto
    orden = sorted(particiones)

    # Una extracción sin cambios produce un DataFrame sin columnas: no es deriva de esquema, se omite
    vacias = [p for p in orden if particiones[p].shape[1] == 0 or len(particiones[p]) == 0]
    usables = [p for p in orden if p not in vacias]
    if not usables:
        raise ValueError("Todas las particiones están vacías: no hay datos que transformar")

    referencia = list(particiones[usables[0]].columns)
    for p in usables[1:]:
        diferencia = set(particiones[p].columns) ^ set(referencia)
        if diferencia:
            raise ValueError(f"Partición {p}: el esquema difiere de la primera "
                             f"({len(diferencia)} columnas distintas); posible cambio en REDCap")

    partes = [particiones[p][referencia].assign(**{_PARTICION: p}) for p in usables]
    combinado = pd.concat(partes, ignore_index=True)

    if combinado[ID].isna().any():
        # groupby descartaría estas filas en silencio: se detiene antes
        raise ValueError(f"{int(combinado[ID].isna().sum())} filas sin {ID}")

    # Cada registro conserva solo las filas de la partición más reciente donde aparece.
    # 1) Para cada record_id se calcula la partición más reciente que lo contiene (el máximo del texto
    #    equivale al más reciente porque el nombre %Y-%m-%dT%H%M%S ordena cronológicamente).
    #    transform (y no agg) repite ese máximo en cada fila del grupo: `ultima` tiene una entrada
    #    por fila de `combinado`, con su mismo índice, por lo que se puede comparar fila a fila.
    ultima = combinado.groupby(ID)[_PARTICION].transform("max")
    # 2) Máscara: una fila se conserva si su partición es la más reciente de SU record_id. Un registro
    #    modificado se queda completo con las filas de la partición nueva (reemplazo por registro,
    #    no por fila) y se descartan todas las de las particiones anteriores.
    vigente = combinado[combinado[_PARTICION] == ultima]

    # A diferencia de `ultima`, esto tiene una entrada por record_id (no por fila): True si el registro
    # aparece en más de una partición, es decir, fue modificado después de su primera extracción.
    # Solo alimenta el resumen; no cambia los datos.
    en_varias = combinado.groupby(ID)[_PARTICION].nunique() > 1
    resumen = {
        "particiones_leidas": len(orden),
        "particiones_vacias_omitidas": len(vacias),
        "filas_totales": len(combinado),
        "filas_vigentes": len(vigente),
        "filas_reemplazadas": len(combinado) - len(vigente),
        "record_id_distintos": int(combinado[ID].nunique()),
        "record_id_en_mas_de_una_particion": int(en_varias.sum()),
    }
    return vigente.drop(columns=_PARTICION).reset_index(drop=True), resumen
