"""
Atenciones duplicadas por regla de negocio: dos registros con llaves distintas, el mismo documento seudonimizado y la misma
fecha y hora de llegada son la misma llegada capturada dos veces. Se conserva uno y el otro sale con todas sus filas hijas
(decisión del 2026-10-28, camino A); la otra opción, pasar las hijas al conservado, mezclaría dos registros y en las
tablas de una fila por atención dejaría dos valores en conflicto.

Se aplica sobre las tablas ya con la llave canónica (`trauma_register_id`), la misma en la base y en las hijas. Solo sale
una atención si está en un grupo repetido y no es la elegida; las filas de las atenciones conservadas no se tocan. Los
documentos vacíos no cuentan: dos pacientes sin documento no se repiten entre sí.

Qué registro se conserva: el que más sabe de la atención (celdas con valor en la tabla base más filas en las tablas
hijas); en empate, el de menor `trauma_register_id`, para que el resultado no dependa del orden de las filas.

Solo deja en el reporte llaves de registro y conteos, nunca el documento ni la fecha.
"""
import pandas as pd

from etl.transform.common.keys import COL_ORIGEN, COL_SISTEMA, COL_TRAUMA
from etl.transform.common.quality import ReporteCalidad

MOTIVO = "duplicado_documento_llegada"


def _informacion(tablas: dict[str, pd.DataFrame], tabla_base: str) -> pd.Series:
    """Cuánto se sabe de cada atención: celdas con valor en la base más filas que tiene en las demás tablas."""
    base = tablas[tabla_base].set_index(COL_TRAUMA)
    informacion = base.drop(columns=[c for c in (COL_ORIGEN, COL_SISTEMA) if c in base.columns]).notna().sum(axis=1)
    for nombre, df in tablas.items():
        if nombre != tabla_base:
            informacion = informacion.add(df[COL_TRAUMA].value_counts(), fill_value=0)
    return informacion.reindex(base.index).astype("int64")


def retirar_atenciones_duplicadas(tablas: dict[str, pd.DataFrame], tabla_base: str, columnas: tuple[str, ...],
                                  reporte: ReporteCalidad) -> dict[str, pd.DataFrame]:
    """
    Quita de todas las tablas las atenciones repetidas en `columnas` de la tabla base, salvo la elegida de cada grupo.

    Args:
        tablas: tablas con `trauma_register_id` (salida de `aplicar_llaves`).
        columnas: la combinación que identifica la misma llegada (documento seudonimizado y fecha y hora de llegada).

    Returns:
        Tablas nuevas, sin las atenciones retiradas (la entrada no se modifica). Sin repetidas, las mismas tablas.

    Raises:
        KeyError: si la base no tiene alguna de `columnas`.
        ValueError: si el retiro cambiara las filas de una atención conservada (no debería pasar).
    """
    base = tablas[tabla_base]
    faltantes = [c for c in columnas if c not in base.columns]
    if faltantes:
        raise KeyError(f"{tabla_base}: faltan las columnas {faltantes} para detectar atenciones duplicadas")

    llegadas = list(columnas)
    evaluables = base.dropna(subset=llegadas)
    repetidas = evaluables[evaluables.duplicated(llegadas, keep=False)]
    if repetidas.empty:
        return tablas

    informacion = _informacion(tablas, tabla_base)
    candidatas = repetidas[[COL_TRAUMA, *llegadas]].assign(informacion=repetidas[COL_TRAUMA].map(informacion))
    candidatas = candidatas.sort_values(["informacion", COL_TRAUMA], ascending=[False, True], kind="stable")
    grupos = candidatas.groupby(llegadas, sort=False)
    candidatas["grupo"] = grupos.ngroup()
    candidatas["conservada"] = grupos[COL_TRAUMA].transform("first")
    candidatas["informacion_conservada"] = grupos["informacion"].transform("first")
    retiradas = candidatas[candidatas[COL_TRAUMA] != candidatas["conservada"]]

    reporte.registrar_atenciones_descartadas([
        {"motivo": MOTIVO, "grupo": int(grupo), "trauma_register_id": retirada, "conservada": conservada,
         "informacion_descartada": int(sabe), "informacion_conservada": int(sabe_conservada)}
        for grupo, retirada, conservada, sabe, sabe_conservada in zip(
            retiradas["grupo"], retiradas[COL_TRAUMA], retiradas["conservada"], retiradas["informacion"],
            retiradas["informacion_conservada"])
    ])

    ids = set(retiradas[COL_TRAUMA])
    conservadas = set(candidatas[COL_TRAUMA]) - ids
    salida = {}
    for nombre, df in tablas.items():
        salida[nombre] = df[~df[COL_TRAUMA].isin(ids)].reset_index(drop=True)
        reporte.registrar_balance(MOTIVO, len(df), nombre, len(salida[nombre]))
        # Garantía del camino A: las filas de las atenciones que se quedan son las mismas antes y después
        if df[COL_TRAUMA].isin(conservadas).sum() != salida[nombre][COL_TRAUMA].isin(conservadas).sum():
            raise ValueError(f"{nombre}: el retiro de duplicados cambió las filas de una atención conservada")
    return salida
