"""Limpieza y tipado genéricos (T1-T2): nombres, vacíos y conversiones auditadas.

Toda conversión usa la columna del propio DataFrame (nunca una Serie de otro DataFrame: pandas alinea
por índice y los valores quedarían desplazados entre episodios) y deja constancia en el ReporteCalidad.
"""
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
import yaml

from etl.transform.common.quality import ReporteCalidad

# Columnas de sistema de REDCap: no se normalizan ni se agrupan por instrumento
COLUMNAS_SISTEMA = frozenset({"record_id", "redcap_event_name",
                              "redcap_repeat_instrument", "redcap_repeat_instance"})


# ---------------------------------------------------------------------------
# T1: nombres y vacíos
# ---------------------------------------------------------------------------

def normalizar_nombre(nombre: str) -> str:
    """Minúsculas, sin tildes, con '_' como único separador."""
    n = unicodedata.normalize("NFKD", str(nombre)).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9a-zA-Z]+", "_", n.strip().lower()).strip("_")


def normalizar_columnas(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Normaliza los nombres de columna. Devuelve el DataFrame y la equivalencia original -> normalizado.

    Raises:
        ValueError: si la normalización hace colapsar dos columnas distintas en el mismo nombre.
    """
    nuevos = [c if c in COLUMNAS_SISTEMA else normalizar_nombre(c) for c in df.columns]
    duplicados = sorted(n for n, veces in Counter(nuevos).items() if veces > 1)
    if duplicados:
        raise ValueError(f"La normalización colapsa columnas distintas: {duplicados}")
    return df.set_axis(nuevos, axis=1), dict(zip(df.columns, nuevos))


def aplicar_renombres(df: pd.DataFrame, equivalencia: dict[str, str],
                      ruta: str | Path) -> tuple[pd.DataFrame, dict[str, str]]:
    """Aplica los renombres semánticos del YAML (nombre normalizado -> nombre corregido).

    La equivalencia devuelta conserva la trazabilidad nombre original de REDCap -> nombre final.

    Raises:
        KeyError: si el YAML renombra una columna que no existe (el origen cambió).
        ValueError: si el nombre destino ya existe en el DataFrame.
    """
    with open(ruta, encoding="utf-8") as f:
        renombres = yaml.safe_load(f) or {}

    ausentes = set(renombres) - set(df.columns)
    if ausentes:
        raise KeyError(f"Renombres sobre columnas inexistentes: {sorted(ausentes)}")
    colision = set(renombres.values()) & (set(df.columns) - set(renombres))
    if colision:
        raise ValueError(f"El destino ya existe en el DataFrame: {sorted(colision)}")

    equivalencia = {orig: renombres.get(norm, norm) for orig, norm in equivalencia.items()}
    return df.rename(columns=renombres), equivalencia


def renombrar_columnas(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str,
                       mapa: dict[str, str], motivo: str) -> pd.DataFrame:
    """Renombra columnas de un bloque y deja constancia en el reporte. Falla si el origen no existe
    o si el destino ya existe."""
    ausentes = set(mapa) - set(df.columns)
    if ausentes:
        raise KeyError(f"{bloque}: renombres sobre columnas inexistentes: {sorted(ausentes)}")
    colision = set(mapa.values()) & (set(df.columns) - set(mapa))
    if colision:
        raise ValueError(f"{bloque}: el destino ya existe: {sorted(colision)}")
    for original, nuevo in mapa.items():
        reporte.registrar_renombre(bloque, original, nuevo, motivo)
    return df.rename(columns=mapa)


def eliminar_columnas(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, columnas: list[str],
                      motivo: str) -> pd.DataFrame:
    """Quita columnas completas y deja constancia en el reporte de cada una con cuántas filas tenían valor (solo el
    conteo). Falla si una columna no existe (cambio del origen)."""
    ausentes = sorted(set(columnas) - set(df.columns))
    if ausentes:
        raise KeyError(f"{bloque}: columnas a eliminar inexistentes: {ausentes}")
    for col in columnas:
        reporte.registrar_exclusion(bloque, col, int(df[col].notna().sum()), motivo)
    return df.drop(columns=columnas)


def vacios_a_nulo(df: pd.DataFrame) -> pd.DataFrame:
    """Celdas vacías o solo con espacios -> nulo real. Es previo a cualquier verificación:
    `dropna`, `duplicated` y `nunique` no reconocen un vacío textual como nulo."""
    return df.replace(r"^\s*$", pd.NA, regex=True)


# ---------------------------------------------------------------------------
# T2: conversiones auditadas
# ---------------------------------------------------------------------------

def verificar_tasa_no_convertibles(bloque: str, col: str, no_convertibles: int, antes: int,
                                   maximo: float) -> None:
    """Se detiene ANTES de asignar si casi nada se convierte (formato o tipo equivocado).

    Sin esta guarda, un formato de fecha incorrecto anula la columna y la auditoría lo explica como
    'no_convertibles' (conserva = True), de modo que la pérdida pasaría inadvertida.
    """
    if antes and no_convertibles / antes > maximo:
        raise ValueError(f"{bloque}.{col}: {no_convertibles} de {antes} valores no se pudieron convertir "
                         f"({no_convertibles / antes:.0%} > {maximo:.0%}); revisar el formato o el tipo")


def convertir_numerico(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str,
                       tipo: str = "Float64", entero: bool = False,
                       rango: tuple[float, float] | None = None,
                       max_no_convertibles: float = 0.5,
                       invalidar_no_enteros: bool = False) -> None:
    """Convierte df[col] a numérico.

    - entero: contrato de la columna; si llega un decimal el origen cambió y se detiene.
    - invalidar_no_enteros: con entero, en lugar de detenerse el decimal se invalida (NA), se reporta como regla
      y la auditoría lo cuenta como no convertible (al tipo entero). Solo para columnas autorizadas una a una.
    - rango: dominio válido; los valores fuera se invalidan (NA) y se reportan, no se corrigen.
    """
    original = df[col]
    numerico = pd.to_numeric(original, errors="coerce")
    no_convertibles = int((original.notna() & numerico.isna()).sum())
    verificar_tasa_no_convertibles(bloque, col, no_convertibles, int(original.notna().sum()),
                                   max_no_convertibles)

    if entero:
        decimal = numerico.notna() & (numerico % 1 != 0)
        no_enteros = int(decimal.sum())
        if no_enteros and not invalidar_no_enteros:
            raise ValueError(f"{bloque}.{col}: {no_enteros} valores no enteros; el contrato exige enteros")
        if invalidar_no_enteros:
            reporte.reportar_regla(bloque, f"{col} con decimal (invalidado)", numerico.notna(), decimal,
                                   reporte.llaves(df), [col])
            numerico = numerico.mask(decimal)
            no_convertibles += no_enteros

    fuera_de_rango = bajo_minimo = sobre_maximo = 0
    if rango is not None:
        fuera = numerico.notna() & ~numerico.between(*rango)
        fuera_de_rango = int(fuera.sum())
        bajo_minimo, sobre_maximo = int((numerico < rango[0]).sum()), int((numerico > rango[1]).sum())
        # Fuera del dominio válido: se invalida; las llaves permiten localizar el registro y corregirlo en la fuente
        reporte.detallar(bloque, f"{col} fuera de rango (invalidado)", "invalidada", col, reporte.llaves(df), fuera, [col])
        numerico = numerico.mask(fuera)

    df[col] = numerico.astype(tipo)
    reporte.registrar_auditoria(bloque, col, original, df[col], no_convertibles, fuera_de_rango,
                                bajo_minimo, sobre_maximo)


def convertir_fecha(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str, formato: str,
                    max_no_convertibles: float = 0.5) -> None:
    """Convierte df[col] a datetime con formato explícito, declarado por columna; los no convertibles se cuentan."""
    original = df[col]
    fecha = pd.to_datetime(original, format=formato, errors="coerce")
    no_convertibles = int((original.notna() & fecha.isna()).sum())
    verificar_tasa_no_convertibles(bloque, col, no_convertibles, int(original.notna().sum()),
                                   max_no_convertibles)

    df[col] = fecha
    reporte.registrar_auditoria(bloque, col, original, df[col], no_convertibles)


def convertir_duracion(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str,
                       rango_minutos: tuple[float, float] | None = None,
                       max_no_convertibles: float = 0.5) -> None:
    """Convierte una duración en texto HH:MM:SS a minutos (Float64).

    Los segundos se conservan como fracción de minuto ('00:00:30' = 0.5). Un formato distinto no se
    convierte y queda contado; los valores fuera de rango_minutos se invalidan (NA) y se reportan.
    """
    original = df[col]
    duracion = pd.to_timedelta(original, errors="coerce")
    no_convertibles = int((original.notna() & duracion.isna()).sum())
    verificar_tasa_no_convertibles(bloque, col, no_convertibles, int(original.notna().sum()),
                                   max_no_convertibles)

    minutos = duracion.dt.total_seconds() / 60
    fuera_de_rango = bajo_minimo = sobre_maximo = 0
    if rango_minutos is not None:
        fuera = minutos.notna() & ~minutos.between(*rango_minutos)
        fuera_de_rango = int(fuera.sum())
        bajo_minimo = int((minutos < rango_minutos[0]).sum())
        sobre_maximo = int((minutos > rango_minutos[1]).sum())
        minutos = minutos.mask(fuera)

    df[col] = minutos.astype("Float64")
    reporte.registrar_auditoria(bloque, col, original, df[col], no_convertibles, fuera_de_rango,
                                bajo_minimo, sobre_maximo)


def convertir_resultado_binario(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str,
                                positivo: str = "POSITIVO", negativo: str = "NEGATIVO",
                                max_no_convertibles: float = 0.5) -> None:
    """Dominio cerrado {negativo, positivo} -> boolean nullable (positivo = True).

    Lo que no pertenece al dominio queda en NA y se cuenta. Una celda vacía NO se imputa como
    negativa: significa que no se registró el examen.
    """
    original = df[col]
    texto = original.astype("string")
    resultado = pd.Series(pd.NA, index=texto.index, dtype="boolean")  # índice del propio bloque
    resultado[(texto == positivo).fillna(False)] = True
    resultado[(texto == negativo).fillna(False)] = False
    no_convertibles = int((original.notna() & resultado.isna()).sum())
    verificar_tasa_no_convertibles(bloque, col, no_convertibles, int(original.notna().sum()),
                                   max_no_convertibles)

    df[col] = resultado
    reporte.registrar_auditoria(bloque, col, original, df[col], no_convertibles)


def registrar_derivada(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str,
                       col_origen: str, col_derivada: str) -> None:
    """Variable calculada: todo valor de origen debe producir un valor derivado."""
    reporte.registrar_auditoria(bloque, col_derivada, df[col_origen], df[col_derivada])


def registrar_estandarizacion(reporte: ReporteCalidad, bloque: str, col: str, original: pd.Series,
                              resultado: pd.Series) -> int:
    """Recodificacion contra un catalogo (texto libre -> valor oficial): audita la conservacion de `col`.

    Los valores informados que quedan vacios por no pertenecer al dominio cuentan como no convertibles, de modo que
    se cumple no_nulos_antes == no_nulos_despues + no_convertibles. `original` es una Series porque el valor de
    origen puede venir de varias columnas consolidadas. Un relleno posterior (p. ej. completar el departamento desde
    el municipio) agrega valores y se registra aparte con `registrar_correccion`. Devuelve los no convertibles.
    """
    no_convertibles = int((original.notna() & resultado.isna()).sum())
    reporte.registrar_auditoria(bloque, col, original, resultado, no_convertibles=no_convertibles)
    return no_convertibles


def derivar_duracion_seg(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str,
                         col_inicio: str, col_fin: str, nombre: str) -> None:
    """Crea `nombre` (Int64, segundos) como fin - inicio; NA si falta una fecha o la duración es negativa.

    Una sola columna en segundos enteros: exacta, sumable y compacta. El formato HH:MM:SS no se almacena
    (ver formatear_hms). Las negativas no se corrigen ni se invierten: se invalidan y se cuentan.
    """
    inicio, fin = df[col_inicio], df[col_fin]
    ambas = inicio.notna() & fin.notna()
    segundos = (fin - inicio).dt.total_seconds().round()
    negativas = ambas & (segundos < 0)

    df[nombre] = segundos.mask(negativas).astype("Int64")
    reporte.registrar_auditoria(bloque, nombre, segundos.where(ambas), df[nombre],
                                fuera_de_rango=int(negativas.sum()), bajo_minimo=int(negativas.sum()))


def formatear_hms(segundos: pd.Series) -> pd.Series:
    """Texto HH:MM:SS solo para mostrar (no se agrega al DataFrame). Las horas pueden superar 24."""
    horas = (segundos // 3600).astype("string").str.zfill(2)
    minutos = ((segundos % 3600) // 60).astype("string").str.zfill(2)
    resto = (segundos % 60).astype("string").str.zfill(2)
    return horas + ":" + minutos + ":" + resto
