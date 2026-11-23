"""Texto libre de sustancias de abuso, compartido por REDCap y el Excel histórico.

Las correcciones viven en config/catalogos/sustancias_correcciones.yaml. Solo se corrigen errores ortográficos de
una palabra; no se unen sinónimos ni se unifican las negaciones (NIEGA, NINGUNA, NINGUNO y NO conservan su texto).
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd
import yaml

from etl.transform.common.cleaning import registrar_estandarizacion
from etl.transform.common.quality import ReporteCalidad

RUTA_CORRECCIONES = Path(__file__).resolve().parents[3] / "config" / "catalogos" / "sustancias_correcciones.yaml"


def cargar_correcciones(ruta: Path = RUTA_CORRECCIONES) -> dict:
    """Devuelve {'correcciones': {...}, 'frases': {...}, 'fuera_de_dominio': set(...)}."""
    cfg = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return {"correcciones": cfg.get("correcciones") or {}, "frases": cfg.get("frases") or {},
            "fuera_de_dominio": set(cfg.get("fuera_de_dominio") or [])}


def limpiar_texto_sustancia(valor, catalogo: dict):
    """MAYÚSCULAS, sin tildes (la Ñ se conserva), espacios colapsados, errores de escritura corregidos palabra por
    palabra y sin signos al final. "No especificado" y "desconocido" se unifican en género y número solo cuando son
    el valor completo. Un texto formado solo por signos queda vacío."""
    if pd.isna(valor):
        return valor
    correcciones, frases = catalogo["correcciones"], catalogo["frases"]
    t = str(valor).replace("´", "").replace("ñ", "#").replace("Ñ", "#")   # acento suelto fuera; la eñe se conserva
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c)).upper().replace("#", "Ñ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"[A-ZÑ]+", lambda m: correcciones.get(m.group(), m.group()), t)
    for error, correcta in frases.items():
        t = t.replace(error, correcta)
    t = re.sub(r"[\s.,|-]+$", "", t)
    t = "NO ESPECIFICADO" if re.fullmatch(r"NO ESPECIFICAD[AO]S?", t) else t
    t = "DESCONOCIDO" if re.fullmatch(r"DESCONOCID[AO]S?", t) else t
    return t if t else pd.NA


def estandarizar_sustancias(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str,
                            catalogo: dict | None = None) -> None:
    """Limpia `col` en el lugar, invalida los valores fuera de dominio y deja constancia en el reporte.

    Auditoría: un valor informado que queda vacío (fuera de dominio o solo signos) cuenta como no convertible, de
    modo que no hay pérdidas sin explicar. Correcciones: filas con texto cambiado y filas invalidadas por dominio.
    """
    catalogo = catalogo or cargar_correcciones()
    original = df[col].copy()
    limpio = original.map(lambda v: limpiar_texto_sustancia(v, catalogo))
    fuera = limpio.isin(catalogo["fuera_de_dominio"]).fillna(False).astype(bool)

    cambiadas = int((original.notna() & limpio.notna() & ~fuera & (original != limpio)).sum())
    reporte.registrar_correccion(bloque, col, "texto estandarizado (mayusculas, sin tildes, errores de escritura)",
                                 cambiadas, "estandarizado")
    reporte.registrar_correccion(bloque, col, "valor que no es una sustancia de abuso (fuera de dominio)",
                                 int(fuera.sum()), "invalidado (NA)")

    df[col] = limpio.mask(fuera).astype("string")
    registrar_estandarizacion(reporte, bloque, col, original, df[col])
