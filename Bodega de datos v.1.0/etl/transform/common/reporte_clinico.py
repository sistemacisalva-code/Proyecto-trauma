"""
Reporte para quien corrige (el personal médico): qué registros hay que revisar, en qué instrumento y campos, por qué y
qué hizo la transformación con el dato. Se escribe como `para_correccion.md` (agrupado por registro) y
`para_correccion.csv` (para filtrar en Excel), a partir de `detalle_filas`.

**Contiene llaves de registros** (no valores): es un documento confidencial, para personal autorizado a abrir esos
registros en la fuente. No es el reporte para compartir (`reporte.md`, que solo trae conteos). Los archivos quedan en
`data/quality_reports/`, fuera de Git. El médico abre el registro en la fuente y ve el valor ahí: este reporte no lo copia.
"""
import pandas as pd

from etl.transform.common.quality import ReporteCalidad
from etl.transform.common.reporte_md import _tabla

COLUMNAS_CSV = ["llave", "instrumento", "campos", "motivo", "tipo", "que_se_hizo", "filas", "corregido"]
FUENTES_LEGIBLES = {"redcap": "REDCap", "excel": "el Excel histórico"}


def _que_se_hizo(tipo: str, columna) -> str:
    if tipo == "corregida":
        return f"Se dejó vacío «{columna}» en el staging (el dato original sigue en la fuente); corregir en la fuente"
    if tipo == "invalidada":
        return f"El valor de «{columna}» estaba fuera del dominio válido y se dejó vacío; corregir en la fuente"
    return "Se conservó el dato; revisar y corregir en la fuente si es un error"


def _instrumento(bloque: str, campos: str) -> str:
    """El instrumento (u hoja) donde se corrige: el prefijo del primer campo si lo trae, o el bloque de la regla."""
    primero = campos.split("; ")[0] if campos else ""
    return primero.split(".")[0] if "." in primero else bloque


def tabla_para_correccion(reporte: ReporteCalidad) -> pd.DataFrame:
    """Una fila por registro y regla, ordenada por registro, con las columnas de COLUMNAS_CSV (vacía si no hay casos)."""
    detalle = reporte.tabla("detalle_filas")
    if detalle.empty:
        return pd.DataFrame(columns=COLUMNAS_CSV)
    tabla = pd.DataFrame({
        "llave": detalle["llave"].astype(str),
        "instrumento": [_instrumento(b, c) for b, c in zip(detalle["bloque"], detalle["campos"].fillna(""))],
        "campos": detalle["campos"].fillna(""),
        "motivo": detalle["regla"],
        "tipo": detalle["tipo"],
        "que_se_hizo": [_que_se_hizo(t, c) for t, c in zip(detalle["tipo"], detalle["columna"])],
        "filas": detalle["filas"],
        "corregido": "",
    })
    # Orden natural de la llave: 2 antes que 10
    orden = tabla["llave"].map(lambda x: (len(x), x))
    return tabla.assign(_o=orden).sort_values(["_o", "instrumento", "motivo"]).drop(columns="_o").reset_index(drop=True)


def construir_para_correccion(reporte: ReporteCalidad, fuente: str, run_id: str) -> tuple[str, pd.DataFrame]:
    """
    El reporte para quien corrige: (Markdown, tabla para el CSV). El Markdown agrupa por registro; la tabla trae una fila
    por registro y regla con una columna `corregido` vacía para anotar el avance.
    """
    tabla = tabla_para_correccion(reporte)
    fuente_legible = FUENTES_LEGIBLES.get(fuente, fuente)
    secciones = [
        f"# Casos para corregir: {fuente}",
        f"> **CONFIDENCIAL.** Contiene llaves de registros (sin valores). Solo para el personal autorizado a abrir esos "
        f"registros en {fuente_legible}. No lo compartas, no lo subas a ningún repositorio ni a la nube y bórralo al "
        "terminar. Se regenera en cada transformación.",
        f"Corrida `{run_id}`. La llave es la del registro en {fuente_legible}"
        + (" (`record_id`); en la bodega es `RC-<record_id>`." if fuente == "redcap" else
           " (`traumaregisterrecordid`); en la bodega es `EX-<id>`."),
        "**Cómo usarlo:** busque el registro por su llave, abra el instrumento indicado y revise los campos. La columna "
        "«Qué se hizo» dice qué pasó con el dato en el staging: en todos los casos el dato original sigue intacto en la "
        "fuente, y solo se corrige allí. El CSV (`para_correccion.csv`) trae lo mismo con una columna `corregido` para "
        "anotar el avance.",
    ]
    if tabla.empty:
        secciones.append("No hay registros marcados en esta corrida.")
        return "\n\n".join(secciones) + "\n", tabla

    por_tipo = tabla.groupby("tipo")["llave"].nunique()
    secciones.append(f"**Resumen:** {tabla['llave'].nunique()} registros con al menos un caso; " + "; ".join(
        f"{n} con casos «{tipo}»" for tipo, n in por_tipo.items()) + ".")
    for llave, grupo in tabla.groupby("llave", sort=False):
        secciones.append(f"### Registro {llave}\n" + _tabla(
            ["Instrumento", "Campos", "Motivo", "Qué se hizo", "Filas"],
            grupo[["instrumento", "campos", "motivo", "que_se_hizo", "filas"]].values.tolist()))
    return "\n\n".join(secciones) + "\n", tabla
