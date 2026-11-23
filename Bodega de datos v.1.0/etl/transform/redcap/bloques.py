"""División del export de REDCap en un bloque por instrumento mediante los marcadores `*_complete`.

REDCap cierra cada instrumento con una columna `<instrumento>_complete` y conserva el orden del
formulario, por lo que esos marcadores delimitan los grupos de columnas.
"""
import pandas as pd

from etl.transform.common.cleaning import COLUMNAS_SISTEMA

CLAVE = ["record_id", "redcap_repeat_instrument", "redcap_repeat_instance"]

# Identificadores directos o cuasi-identificadores sin uso analítico: se excluyen al dividir.
# (numero_de_identificacion no está aquí: se reemplaza por documento_seudonimo antes de dividir.)
EXCLUIR_DEL_DW = ["nombre", "apellido_paterno", "apellido_materno", "direccion", "fecha_de_nacimiento"]

# Contrato del transformer y ORDEN de procesamiento: nombres tras aplicar los renombres del YAML.
INSTRUMENTOS_ESPERADOS = (
    "informacion_demografica", "motivo_de_consulta", "comorbilidades",
    "mecanismo_de_lesion", "signos_vitales", "examen_fisico",
    "puntuacion_de_severidad", "imagenes", "laboratorio", "hospitalizacion",
    "complicaciones", "cie_10_diagnosticos", "procedimientos", "liquidos", "uci",
)

# Instrumentos cuya transformación necesita bloques ya transformados (deben ir antes en el orden)
DEPENDENCIAS = {
    "procedimientos": ("informacion_demografica", "hospitalizacion"),
}


def validar_dependencias() -> None:
    """Falla si algún instrumento se procesaría antes que uno de los que necesita."""
    for nombre, requeridos in DEPENDENCIAS.items():
        for req in requeridos:
            if INSTRUMENTOS_ESPERADOS.index(req) >= INSTRUMENTOS_ESPERADOS.index(nombre):
                raise ValueError(f"'{nombre}' depende de '{req}', que se procesa después")


def agrupar_por_instrumento(columnas) -> dict[str, list[str]]:
    grupos, actual = {}, []
    for c in columnas:
        if c in COLUMNAS_SISTEMA:
            continue
        actual.append(c)
        if c.endswith("_complete"):
            grupos[c.removesuffix("_complete")] = actual
            actual = []
    if actual:  # columnas posteriores al último marcador
        grupos["_sin_instrumento"] = actual
    return grupos


def validar_grupos(grupos: dict[str, list[str]], columnas) -> None:
    # raise y no assert: los assert se desactivan con python -O
    asignadas = [c for cols in grupos.values() for c in cols]
    if len(asignadas) != len(set(asignadas)):
        raise ValueError("Hay columnas asignadas a más de un instrumento")

    sin_asignar = set(columnas) - COLUMNAS_SISTEMA - set(asignadas)
    if sin_asignar:
        raise ValueError(f"Columnas sin instrumento: {sorted(sin_asignar)}")

    # Un cambio en el diccionario de datos de REDCap debe detener el pipeline, no propagarse
    faltantes = set(INSTRUMENTOS_ESPERADOS) - set(grupos)
    inesperados = set(grupos) - set(INSTRUMENTOS_ESPERADOS)
    if faltantes or inesperados:
        raise ValueError(f"Instrumentos faltantes: {sorted(faltantes)} | inesperados: {sorted(inesperados)}")


def _columnas_de_datos(columnas: list[str]) -> list[str]:
    """Columnas del instrumento que cuentan como dato: sin identificadores excluidos ni marcador `_complete`."""
    return [c for c in columnas if c not in EXCLUIR_DEL_DW and not c.endswith("_complete")]


def extraer_bloque(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    datos = _columnas_de_datos(columnas)
    sub = df[[c for c in CLAVE if c in df.columns] + datos]
    # Solo filas con algún dato del instrumento: el resto son nulos estructurales. El índice se reinicia:
    # las conversiones usan siempre la columna del propio bloque (nunca una Serie de otro DataFrame).
    return sub.dropna(subset=datos, how="all").reset_index(drop=True)


def dividir_en_bloques(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """df completo -> un DataFrame por instrumento, en el orden de INSTRUMENTOS_ESPERADOS."""
    grupos = agrupar_por_instrumento(df.columns)
    validar_grupos(grupos, df.columns)
    return {nombre: extraer_bloque(df, grupos[nombre]) for nombre in INSTRUMENTOS_ESPERADOS}


MARCADOR_VACIO = "(vacío)"


def resumir_descartes(df: pd.DataFrame) -> list[dict]:
    """Cuenta, por instrumento y por valor de su marcador `<instrumento>_complete`, las filas que
    `extraer_bloque` descarta por no tener ningún dato propio (instrumento vacío: nulo estructural).

    Sirve para que el descarte no sea invisible: por instrumento, filas del bloque + filas descartadas
    = filas del DataFrame. Un marcador lleno (p. ej. "Complete") en una fila descartada es un
    formulario abierto o cerrado sin respuestas; un marcador vacío es una fila de otro instrumento
    (nulo estructural), que es la inmensa mayoría en un export longitudinal. Solo agregados: no hay
    valores de pacientes. El marcador se cuenta como texto, tal como llegue del export.

    `en_instancia_repetible` indica cuántas de las filas descartadas tienen número de instancia, es decir, son
    instancias repetibles creadas sin datos y no la fila principal del episodio. Permite distinguir un
    formulario vacío de un instrumento repetible de uno no repetible dejado sin diligenciar.
    """
    grupos = agrupar_por_instrumento(df.columns)
    validar_grupos(grupos, df.columns)
    en_instancia = (df["redcap_repeat_instance"].notna() if "redcap_repeat_instance" in df.columns
                    else pd.Series(False, index=df.index))
    filas = []
    for nombre in INSTRUMENTOS_ESPERADOS:
        sin_datos = df[_columnas_de_datos(grupos[nombre])].isna().all(axis=1)
        marcador = df.loc[sin_datos, f"{nombre}_complete"].astype("string").fillna(MARCADOR_VACIO)
        conteos = en_instancia[sin_datos].groupby(marcador).agg(["size", "sum"]).sort_index()
        for valor, fila in conteos.iterrows():
            filas.append({"instrumento": nombre, "marcador": str(valor),
                          "filas_descartadas": int(fila["size"]), "en_instancia_repetible": int(fila["sum"])})
    return filas


def columnas_en_conflicto(sub: pd.DataFrame, datos: list[str]) -> int:
    """Columnas con más de un valor distinto dentro de un mismo record_id."""
    return int((sub.groupby("record_id")[datos].nunique(dropna=True) > 1).any().sum())


def resumir_bloques(bloques: dict[str, pd.DataFrame]) -> list[dict]:
    """Solo agregados por instrumento: no expone valores de pacientes."""
    filas = []
    for nombre, sub in bloques.items():
        datos = [c for c in sub.columns if c not in CLAVE]
        max_filas = int(sub.groupby("record_id").size().max()) if len(sub) else 0
        repetible = ("redcap_repeat_instance" in sub.columns
                     and bool(sub["redcap_repeat_instance"].notna().any()))
        filas.append({
            "instrumento": nombre,
            "n_columnas_datos": len(datos),
            "n_filas": len(sub),
            "n_record_id": sub["record_id"].nunique(),
            "max_filas_por_record": max_filas,
            "repetible": repetible,
            # Un instrumento no repetible con más de una fila por episodio exige revisión
            "columnas_en_conflicto": columnas_en_conflicto(sub, datos) if (not repetible and max_filas > 1) else 0,
        })
    return filas
