"""lugar_del_evento del Excel histórico: texto libre llevado a las etiquetas de REDCap por palabras clave.

Reglas en config/catalogos/lugar_del_evento.yaml (palabras clave por etiqueta; el orden es la prioridad). El texto
original se descarta: lo que no tiene ninguna palabra clave queda en la etiqueta «sin clasificar», de modo que el campo
no conserva nombres de lugares ni de personas.
"""
from pathlib import Path

import pandas as pd
import yaml

from etl.transform.common.geografia import normalizar_texto
from etl.transform.common.quality import ReporteCalidad

RUTA_REGLAS = Path(__file__).resolve().parents[3] / "config" / "catalogos" / "lugar_del_evento.yaml"


def _raiz(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _tokens(texto) -> tuple[str, ...]:
    return tuple(_raiz(t) for t in normalizar_texto(texto).split())


def cargar_reglas(ruta: Path = RUTA_REGLAS) -> dict:
    """Lee el YAML y valida que toda etiqueta esté en el dominio y que ninguna regla quede sin palabras clave."""
    cfg = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    dominio = set(cfg["etiquetas"])
    if cfg["etiqueta_sin_clasificar"] not in dominio:
        raise ValueError("etiqueta_sin_clasificar no está en el dominio de etiquetas")
    reglas = []
    for regla in cfg["reglas"]:
        if regla["etiqueta"] not in dominio:
            raise ValueError(f"Etiqueta fuera del dominio de REDCap: {regla['etiqueta']}")
        if not regla["palabras"]:
            raise ValueError(f"La regla de {regla['etiqueta']} no tiene palabras clave")
        reglas.append((regla["etiqueta"], {_tokens(p) for p in regla["palabras"]}))
    return {"sin_clasificar": cfg["etiqueta_sin_clasificar"], "etiquetas": dominio, "reglas": reglas}


def _clasificar(texto, reglas: dict) -> str | None:
    """Etiqueta de la primera regla con una palabra clave presente en `texto`, o None si ninguna coincide."""
    tokens = _tokens(texto)
    for etiqueta, palabras in reglas["reglas"]:
        for palabra in palabras:
            n = len(palabra)
            if any(tokens[i:i + n] == palabra for i in range(len(tokens) - n + 1)):
                return etiqueta
    return None


def mapear_lugar_del_evento(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str,
                            reglas: dict | None = None) -> pd.Series:
    """Reemplaza el texto de `col` por una etiqueta de REDCap; devuelve los textos (distintos) sin palabra clave.

    Vacío queda vacío. Un texto sin palabra clave queda en «sin clasificar» y se cuenta con una regla de calidad; un
    texto que ya era «sin clasificar» no cuenta como incumplimiento. Cada etiqueta asignada por palabra clave se
    registra como corrección y la auditoría confirma que no se pierden valores informados.
    """
    reglas = cargar_reglas() if reglas is None else reglas
    por_defecto = reglas["sin_clasificar"]
    original = df[col].copy()
    informado = original.notna()

    asignada, sin_palabra, con_palabra = {}, set(), set()
    for texto in original[informado].unique():
        etiqueta = _clasificar(texto, reglas)
        if etiqueta is not None:
            con_palabra.add(texto)
        else:
            etiqueta = por_defecto
            if normalizar_texto(texto) != normalizar_texto(por_defecto):
                sin_palabra.add(texto)
        asignada[texto] = etiqueta
    resultado = original.map(asignada).astype("string")
    incumple = informado & original.isin(sin_palabra)

    for etiqueta, n in resultado[original.isin(con_palabra)].value_counts().items():
        reporte.registrar_correccion(bloque, col, f"texto llevado a la etiqueta de REDCap «{etiqueta}» (palabra clave)",
                                     int(n), "mapeado")
    reporte.reportar_regla(bloque, f"{col} sin palabra clave (se descarta el texto y queda «{por_defecto}»)",
                           informado, incumple, reporte.llaves(df), [col])
    df[col] = resultado
    reporte.registrar_auditoria(bloque, col, original, resultado, no_convertibles=0)
    return pd.Series(sorted(sin_palabra), dtype="string", name=col)
