"""
Reporte de calidad de la transformación en Markdown (`reporte.md`), una vista legible y compartible de las tablas del
reporte. Solo contiene conteos y nombres de bloques, columnas y reglas: nunca valores ni llaves de registros. Las llaves
están únicamente en `detalle_filas.parquet` y `atenciones_descartadas.parquet`, que no se resumen aquí más que en
número. La fuente de verdad sigue siendo cada tabla en Parquet; este archivo se deriva de ellas.
"""
import pandas as pd

from etl.transform.common.quality import ReporteCalidad

TITULO = "Reporte de calidad de la transformación"


def _celda(valor) -> str:
    if valor is None or (not isinstance(valor, (list, dict)) and pd.isna(valor)):
        return ""
    return str(valor).replace("|", "\\|").replace("\n", " ")


def _tabla(encabezados: list[str], filas: list[list]) -> str:
    lineas = ["| " + " | ".join(encabezados) + " |", "|" + "|".join("---" for _ in encabezados) + "|"]
    lineas += ["| " + " | ".join(_celda(c) for c in fila) + " |" for fila in filas]
    return "\n".join(lineas)


def _porcentaje(parte: int, total: int) -> str:
    return f"{100 * parte / total:.2f} %" if total else ""


def construir_markdown(reporte: ReporteCalidad, fuente: str, run_id: str, transformed_at: str,
                       filas: dict[str, int]) -> str:
    """
    El reporte consolidado de una corrida: tablas de salida, balance de filas, atenciones retiradas por duplicado
    (solo cuántas), reglas que marcaron casos, correcciones, pérdidas por conversión, columnas excluidas y duplicados
    (solo conteos). Nada que identifique un registro.
    """
    reglas, correcciones = reporte.tabla("reglas"), reporte.tabla("correcciones")
    auditoria, exclusiones = reporte.tabla("auditoria"), reporte.tabla("exclusiones")
    balance, duplicados = reporte.tabla("balance_filas"), reporte.tabla("resumen_duplicados")
    detalle = reporte.tabla("detalle_filas")
    secciones = [
        f"# {TITULO}: {fuente}",
        f"Corrida `{run_id}` (transformada el {transformed_at}). Solo conteos y nombres: este archivo no contiene "
        "valores ni llaves de registros, así que se puede compartir. Las llaves de los registros marcados están en "
        "`detalle_filas.parquet`, que no se comparte (`scripts/casos_para_corregir.py`).",
        "## 1. Tablas de salida (filas)\n" + _tabla(["Tabla", "Filas"], [[t, n] for t, n in filas.items()]),
    ]

    if not balance.empty:
        secciones.append("## 2. Balance de filas por hoja de origen\n" + _tabla(
            ["Origen", "Filas de entrada", "Tabla", "Filas de salida"],
            balance[["origen", "filas_entrada", "tabla", "filas_salida"]].values.tolist()))

    retiradas = len(reporte.atenciones_descartadas)
    secciones.append(f"## 3. Atenciones retiradas por duplicado\n{retiradas} atenciones retiradas "
                     "(sus llaves están en `atenciones_descartadas.parquet`).")

    if reglas.empty:
        secciones.append("## 4. Reglas que marcaron casos\nNo hay reglas registradas.")
    else:
        con_casos = reglas[reglas["filas_que_incumplen"] > 0].sort_values("filas_que_incumplen", ascending=False)
        sin_casos = len(reglas) - len(con_casos)
        secciones.append(
            f"## 4. Reglas que marcaron casos\n{len(con_casos)} de {len(reglas)} reglas marcaron casos; {sin_casos} "
            "no marcaron ninguno. Las reglas que solo reportan no modifican el dato.\n\n" + (
                _tabla(["Bloque", "Regla", "Evaluables", "Incumplen", "%"],
                       [[r.bloque, r.regla, r.filas_evaluables, r.filas_que_incumplen,
                         _porcentaje(r.filas_que_incumplen, r.filas_evaluables)] for r in con_casos.itertuples()])
                if len(con_casos) else "Ninguna regla marcó casos."))

    if not correcciones.empty:
        aplicadas = correcciones[correcciones["filas_afectadas"] > 0]
        secciones.append("## 5. Correcciones: datos que una regla invalidó o modificó\n" + (
            _tabla(["Bloque", "Columna", "Regla", "Acción", "Filas afectadas"],
                   aplicadas[["bloque", "columna", "regla", "accion", "filas_afectadas"]].values.tolist())
            if len(aplicadas) else "Ninguna corrección afectó filas."))

    if not auditoria.empty:
        perdidas = auditoria[(auditoria["no_convertibles"] > 0) | (auditoria["fuera_de_rango"] > 0)]
        sin_explicar = int((~auditoria["conserva"]).sum())
        secciones.append(
            "## 6. Conversión de columnas: valores que no se pudieron convertir o quedaron fuera del dominio\n"
            f"{len(auditoria)} columnas auditadas; {sin_explicar} con diferencia sin explicar (debe ser 0).\n\n" + (
                _tabla(["Bloque", "Columna", "No convertibles", "Fuera de rango", "Bajo el mínimo", "Sobre el máximo"],
                       perdidas[["bloque", "columna", "no_convertibles", "fuera_de_rango", "bajo_minimo",
                                 "sobre_maximo"]].values.tolist())
                if len(perdidas) else "Ninguna columna perdió valores por conversión ni por dominio."))

    if not exclusiones.empty:
        secciones.append("## 7. Columnas excluidas\n" + _tabla(
            ["Bloque", "Columna", "Filas con valor", "Motivo"],
            exclusiones[["bloque", "columna", "filas_con_valor", "motivo"]].values.tolist()))

    if not duplicados.empty:
        secciones.append("## 8. Duplicados marcados (solo conteos)\n" + _tabla(
            ["Bloque", "Nivel", "Filas evaluables", "Filas involucradas", "Combinaciones repetidas"],
            duplicados[["bloque", "nivel", "filas_evaluables", "filas_involucradas",
                        "combinaciones_repetidas"]].values.tolist()))

    if not detalle.empty:
        por_tipo = detalle.groupby("tipo")["llave"].nunique()
        secciones.append("## 9. Registros marcados (solo cuántos)\n" + _tabla(
            ["Tipo", "Registros distintos"], [[tipo, n] for tipo, n in por_tipo.items()]) +
            "\n\nIncumple: la regla lo marcó y el dato se conservó. Corregida o invalidada: el dato se modificó o se "
            "vació. Las llaves están en `detalle_filas.parquet`.")

    return "\n\n".join(secciones) + "\n"
