"""Laboratorio compartido por REDCap y el Excel histórico: rangos, tipo de sangre, sangre en orina y reglas por columna.

Movido sin cambios desde etl/transform/redcap/instrumentos/laboratorio.py (2026-10-21) para que el Excel aplique las
mismas reglas sin importar del paquete de REDCap. Las funciones trabajan sobre una columna del DataFrame que reciben,
así que sirven tanto para el instrumento de REDCap (una fila por examen con todas las columnas) como para el Excel.
"""
import pandas as pd

from etl.transform.common.cleaning import convertir_numerico
from etl.transform.common.quality import ReporteCalidad

RESULTADOS_TOXICOLOGIA = ["anfetaminas", "barbituricos", "benzodiacepinas", "cocaina", "opiaceos",
                          "fenciclidina", "mioglobinuria"]

# Tipos y rangos: PROPUESTA basada en el significado clínico de cada variable. Los rangos son límites de
# plausibilidad para detectar errores de captura, no rangos de referencia; las unidades son las
# convencionales y deben confirmarse. Un valor fuera de rango se invalida (NA) y se reporta.
# Sin rango (None) = unidad por confirmar antes de fijarlo.
ESPECIFICACION_NUMERICA = {
    # columna:           (tipo, entero, rango)             # item y unidad supuesta
    "globulos_blancos":  ("Float64", False, None),         # 2.1  x10^3/uL 
    "hematocrito":       ("Float64", False, (5, 75)),      # 2.2  %
    "hemoglobina":       ("Float64", False, (1, 25)),      # 2.3  g/dL
    "plaquetas":         ("Float64", False, (5, 1500)),    # 2.4  x10^3/uL (unidad confirmada: plaquetas/uL registradas en miles)
    "na":                ("Float64", False, (90, 190)),    # 2.6  mEq/L
    "k":                 ("Float64", False, (1, 12)),      # 2.7  mEq/L
    "cl":                ("Float64", False, (60, 150)),    # 2.8  mEq/L
    "hco3":              ("Float64", False, (2, 60)),      # 2.9  mEq/L
    "bun":               ("Float64", False, (1, 300)),     # 2.10 mg/dL
    "creatinina":        ("Float64", False, (0.1, 25)),    # 2.11 mg/dL
    "glucosa":           ("Float64", False, (10, 1000)),   # 2.12 mg/dL
    "tp":                ("Float64", False, (5, 300)),     # 2.13 segundos
    "tpt":               ("Float64", False, (10, 300)),    # 2.14 segundos
    "inr":               ("Float64", False, (0.5, 20)),    # 2.15 sin unidad
    "pao2":              ("Float64", False, (10, 700)),    # 2.17 mmHg
    "paco2":             ("Float64", False, (5, 200)),     # 2.18 mmHg
    "ph":                ("Float64", False, (6.5, 8.0)),   # 2.19 sin unidad
    "be":                ("Float64", False, (-40, 40)),    # 2.20 mEq/L (admite negativos)
    "deficit_de_base":   ("Float64", False, (-40, 40)),    # 2.21 mEq/L (convención de signo por confirmar)
    "lactato":           ("Float64", False, (0.1, 30)),    # 2.22 mmol/L (unidad confirmada)
}

GRUPOS_SANGUINEOS_VALIDOS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
ESCALA_SANGRE_EN_ORINA = [0, 10, 25, 50, 150, 250]

# Rangos plausibles (PROPUESTA clínica): mientras la unidad no esté confirmada NO se invalida (no van en
# convertir_numerico); se reporta lo que cae fuera de los rangos de AMBAS unidades. Plaquetas y lactato ya
# tienen unidad confirmada (2026-10-19) y pasaron a límite duro en ESPECIFICACION_NUMERICA.
RANGOS_PLAUSIBLES = {
    # columna:            (rango en x10^3/uL, rango en /mm3)
    "globulos_blancos":   ((0.1, 200), (100, 200_000)),
}


def normalizar_tipo_sangre(serie: pd.Series) -> pd.Series:
    """Grupo + Rh en formato canónico ('O+', 'AB-'...); NA si no se puede interpretar."""
    t = serie.astype("string").str.upper().str.replace(r"[\s\.]", "", regex=True)
    grupo = t.str.extract(r"^(AB|A|B|O|0)", expand=False).replace("0", "O")
    rh = pd.Series(pd.NA, index=t.index, dtype="string")
    rh = rh.mask(t.str.contains(r"\+|POS", regex=True).fillna(False), "+")
    rh = rh.mask(t.str.contains(r"-|NEG", regex=True).fillna(False), "-")
    combinado = grupo + rh
    return combinado.where(combinado.isin(GRUPOS_SANGUINEOS_VALIDOS))


def convertir_tipo_sangre(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str,
                          col: str = "tipo_de_sangre_y_factor_rh") -> None:
    """Lo que no se pueda interpretar queda en NA y se cuenta como no convertible."""
    original = df[col]
    df[col] = normalizar_tipo_sangre(original)
    no_interpretables = int((original.notna() & df[col].isna()).sum())
    reporte.registrar_auditoria(bloque, col, original, df[col], no_convertibles=no_interpretables)


def convertir_examenes_numericos(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Tipo y rango de ESPECIFICACION_NUMERICA en las columnas presentes (el Excel no trae todas)."""
    for col, (tipo, entero, rango) in ESPECIFICACION_NUMERICA.items():
        if col in df.columns:
            convertir_numerico(df, reporte, bloque, col, tipo, entero, rango)


def convertir_sangre_en_orina(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str,
                              col: str = "sangre_en_orina") -> None:
    """sangre_en_orina mezcla texto ('neg', 'NEGATIVO') y números de la escala semicuantitativa de la tira reactiva
    (unidad supuesta: eritrocitos/uL; por confirmar). Los negativos se unifican como 0 y el resto del texto queda NA
    y contado en no_convertibles."""
    texto = df[col].astype("string").str.strip().str.upper()
    df[col] = texto.mask(texto.isin(["NEG", "NEGATIVO"]), "0")
    convertir_numerico(df, reporte, bloque, col, "Int64", entero=True, rango=(0, 250))


def convertir_otras_drogas(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str = "otras_drogas") -> None:
    """otras_drogas es nominal (dominio abierto): solo cambia el tipo a texto."""
    original = df[col]
    df[col] = original.astype("string")
    reporte.registrar_auditoria(bloque, col, original, df[col])


def reportar_otras_drogas_multiples(lab: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """otras_drogas (toxicología de laboratorio) con varias sustancias en una celda: solo se reporta. Su destino en la
    bodega sigue sin decidir (atributo, dimensión o puente). No confundir con abuso_de_drogas (bridge_atencion_sustancia)."""
    reporte.reportar_regla(bloque, "otras_drogas con varias sustancias en una celda (separador , ; / o ' Y ')",
                           lab["otras_drogas"].notna(),
                           lab["otras_drogas"].str.contains(r"[,;/]|\sY\s", regex=True).fillna(False), reporte.llaves(lab),
                           ["otras_drogas"])


def reportar_hematocrito_hemoglobina(lab: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Regla de los tres: el hematocrito (%) es aproximadamente 3 veces la hemoglobina (g/dL). Necesita las dos en la
    misma fila (en el Excel, después de juntar los exámenes por toma)."""
    reporte.reportar_regla(bloque, "hematocrito / hemoglobina fuera de [2.5, 3.5]",
                           lab["hematocrito"].notna() & lab["hemoglobina"].notna(),
                           ~(lab["hematocrito"] / lab["hemoglobina"]).between(2.5, 3.5), reporte.llaves(lab),
                           ["hematocrito", "hemoglobina"])


def reportar_escala_orina(lab: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    orina = lab["sangre_en_orina"]
    reporte.reportar_regla(bloque, f"sangre_en_orina fuera de la escala {set(ESCALA_SANGRE_EN_ORINA)}",
                           orina.notna(), ~orina.isin(ESCALA_SANGRE_EN_ORINA), reporte.llaves(lab),
                           ["sangre_en_orina"])


def reportar_unidad_y_rangos_plausibles(lab: pd.DataFrame, reporte: ReporteCalidad, bloque: str) -> None:
    """Unidad de leucocitos sin confirmar: si hay valores de ambos tipos, la unidad está mezclada; y lo que cae fuera
    de los rangos plausibles de las dos unidades (solo se reporta)."""
    for col in ["globulos_blancos"]:
        reporte.reportar_regla(bloque, f"{col} >= 1000 (posible /mm3)", lab[col].notna(), lab[col] >= 1000,
                               reporte.llaves(lab), [col])
        reporte.reportar_regla(bloque, f"{col} < 1000 (posible x10^3/uL)", lab[col].notna(), lab[col] < 1000,
                               reporte.llaves(lab), [col])

    for col, (rango_a, rango_b) in RANGOS_PLAUSIBLES.items():
        en_rango = lab[col].between(*rango_a)
        if rango_b is not None:
            en_rango = en_rango | lab[col].between(*rango_b)
        reporte.reportar_regla(bloque, f"{col} fuera de los rangos plausibles {rango_a}" +
                               (f" o {rango_b}" if rango_b else ""),
                               lab[col].notna(), ~en_rango.fillna(False), reporte.llaves(lab), [col])
