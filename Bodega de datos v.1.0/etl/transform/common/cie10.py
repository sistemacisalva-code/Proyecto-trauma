"""CIE-10 compartido por REDCap y el Excel histórico: el Excel se lleva a las opciones de REDCap.

Catálogo: las opciones de REDCap (config/catalogos/cie10_redcap.csv), una línea "CÓDIGO ETIQUETA" por opción.
- La llave del código es el código sin `*` ni `†`; el valor guardado es siempre la línea completa, con su símbolo.
- Los 6 códigos con dos redacciones del mismo diagnóstico se reducen a la etiqueta canónica (cie10_etiquetas_canonicas.yaml).
- El Excel solo trae texto: se empareja por etiqueta normalizada. Si REDCap ofrece el código con y sin símbolo, el
  Excel va a la versión sin símbolo. Un texto sin pareja se conserva sin código, solo pasado a MAYÚSCULAS (decisión del
  usuario 2026-10-20: corregirlos queda como mejora futura), y se cuenta.
"""
import re
from pathlib import Path

import pandas as pd
import yaml

from etl.transform.common.cleaning import registrar_estandarizacion
from etl.transform.common.geografia import normalizar_texto
from etl.transform.common.quality import ReporteCalidad

CATALOGOS = Path(__file__).resolve().parents[3] / "config" / "catalogos"
RUTA_CATALOGO = CATALOGOS / "cie10_redcap.csv"
RUTA_CANONICAS = CATALOGOS / "cie10_etiquetas_canonicas.yaml"
RUTA_AJUSTES_EXCEL = CATALOGOS / "cie10_excel.yaml"
RUTA_LISTA_COMPLETA = CATALOGOS / "cie10_lista_completa.csv"
SIMBOLOS = r"[*†]"
LONGITUD_LINEA_CORTADA = 55   # la lista completa corta cada línea a ~60 caracteres: desde 55 puede estar incompleta

# Capítulos CIE-10 (primera letra) que admite cada campo; los demás campos admiten cualquiera.
CAPITULOS_POR_CAMPO = {
    "cie10_mecanismos_de_lesiones_de_transito": "V",
    "cie_10_otros_mecanismos_de_lesion_excluye_transito": "VWXY",
}

# Papel del diagnóstico en la hoja 5 del Excel (mecanismo_icd) -> tabla de staging, que lleva el nombre del campo
# CIE-10 de REDCap o, si REDCap no tiene el campo, uno con la misma forma. Cada tabla llega a un rol del puente
# bridge_atencion_cie_10 del modelo completo (ver el comentario de la tabla en 02_tables_completo.sql):
#   Final Diagnosis and Organ Injury Scale -> diagnostico         (diagnóstico definitivo, confirmado)
#   Co-morbidities                         -> comorbilidad        (enfermedad previa)
#   Traffic Injury                         -> mecanismo_transito  (lesión de tránsito, capítulo V)
#   Non-Traffic Injury                     -> otro_mecanismo      (lesión que no es de tránsito)
# El rol complicacion sale de la hoja de complicaciones de hospitalización, no de esta.
PAPEL_A_CAMPO = {
    "Final Diagnosis and Organ Injury Scale": "cie_10_diagnostico_definitivo",
    "Co-morbidities": "cie_10_comorbilidades",
    "Traffic Injury": "cie10_mecanismos_de_lesiones_de_transito",
    "Non-Traffic Injury": "cie_10_otros_mecanismos_de_lesion_excluye_transito",
}
# Papeles que no entran a los modelos y se separan en la tabla codigos_cie10_fuera_de_modelo (decisión del usuario
# 2026-10-20). Reference y Counter Reference describen la remisión entre instituciones, no la atención. Emergency
# Diagnosis (impresión al ingreso, sin campo en REDCap) queda pendiente para una implementación futura como rol
# propio del puente (2026-10-25).
PAPELES_FUERA_DE_MODELO = ("Emergency Diagnosis", "Reference", "Counter Reference")


def _leer_canonicas(ruta: Path) -> dict[str, str]:
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))["etiquetas_canonicas"]


def _leer_lineas(ruta: Path) -> pd.Series:
    return pd.read_csv(ruta, dtype=str)["codigo_cie10"].dropna().str.strip()


def cargar_catalogo(ruta: Path = RUTA_CATALOGO, ruta_canonicas: Path = RUTA_CANONICAS) -> pd.DataFrame:
    """Miembros del catálogo: linea, codigo, clave (código sin símbolo), con_simbolo y norm (etiqueta normalizada).

    Quita la redacción no canónica de los códigos de cie10_etiquetas_canonicas.yaml. Falla si una canónica no existe en
    el catálogo o si una misma etiqueta normalizada apunta a dos códigos distintos (el emparejamiento sería ambiguo).
    """
    lineas = _leer_lineas(ruta)
    canonicas = _leer_canonicas(ruta_canonicas)
    ausentes = sorted(set(canonicas.values()) - set(lineas))
    if ausentes:
        raise ValueError(f"Etiquetas canónicas que no están en el catálogo: {ausentes}")

    cat = pd.DataFrame({"linea": lineas.drop_duplicates().to_numpy()})
    partes = cat["linea"].str.split(" ", n=1)
    cat["codigo"] = partes.str[0]
    cat["clave"] = cat["codigo"].str.replace(SIMBOLOS, "", regex=True)
    cat["con_simbolo"] = cat["codigo"].str.contains(SIMBOLOS, regex=True)
    cat["norm"] = partes.str[1].fillna("").map(normalizar_texto)
    alterna = cat["codigo"].isin(canonicas) & ~cat["linea"].isin(canonicas.values())
    cat = cat[~alterna].reset_index(drop=True)

    ambiguas = cat.groupby("norm")["clave"].nunique()
    ambiguas = sorted(ambiguas[ambiguas > 1].index)
    if ambiguas:
        raise ValueError(f"Etiquetas normalizadas que apuntan a dos códigos: {ambiguas}")
    return cat


def indice_por_texto(catalogo: pd.DataFrame) -> dict[str, str]:
    """{etiqueta normalizada: línea}. Con y sin símbolo comparten etiqueta: gana la versión sin símbolo (7.1)."""
    ordenado = catalogo.sort_values("con_simbolo", kind="stable")
    return dict(ordenado.drop_duplicates("norm")[["norm", "linea"]].to_numpy())


def redacciones_alternas(ruta: Path = RUTA_CATALOGO, ruta_canonicas: Path = RUTA_CANONICAS) -> dict[str, str]:
    """{línea con la redacción no canónica: línea canónica} para los códigos de la decisión 7.2."""
    canonicas = _leer_canonicas(ruta_canonicas)
    lineas = _leer_lineas(ruta)
    codigo = lineas.str.split(" ", n=1).str[0]
    return {linea: canonicas[c] for linea, c in zip(lineas, codigo) if c in canonicas and linea != canonicas[c]}


def cargar_universo(catalogo: pd.DataFrame | None = None, ruta: Path = RUTA_LISTA_COMPLETA) -> pd.DataFrame:
    """Catálogo + los códigos que solo están en la lista completa de REDCap (config/catalogos/cie10_lista_completa.csv).

    La lista completa trae todos los códigos pero con cada línea cortada a unos 60 caracteres (`truncada`); el catálogo
    trae la etiqueta completa solo de los códigos vistos en los datos, y por eso gana cuando el código está en ambos.
    Columnas: linea, codigo, clave, con_simbolo, etiqueta, norm, tokens, truncada.
    """
    catalogo = cargar_catalogo() if catalogo is None else catalogo
    lineas = pd.read_csv(ruta, dtype=str)["linea"].dropna().str.strip()
    partes = lineas.str.split(" ", n=1)
    nuevos = pd.DataFrame({"linea": lineas, "codigo": partes.str[0], "etiqueta": partes.str[1].fillna("")})
    nuevos = nuevos[~nuevos["codigo"].isin(catalogo["codigo"])].drop_duplicates("codigo")
    nuevos["clave"] = nuevos["codigo"].str.replace(SIMBOLOS, "", regex=True)
    nuevos["con_simbolo"] = nuevos["codigo"].str.contains(SIMBOLOS, regex=True)
    nuevos["truncada"] = nuevos["linea"].str.len() >= LONGITUD_LINEA_CORTADA

    base = catalogo[["linea", "codigo", "clave", "con_simbolo"]].copy()
    base["etiqueta"] = base["linea"].str.split(" ", n=1).str[1].fillna("")
    base["truncada"] = False
    universo = pd.concat([base, nuevos], ignore_index=True)
    universo["norm"] = universo["etiqueta"].map(normalizar_texto)
    universo["tokens"] = universo["etiqueta"].map(_tokens)
    return universo


def _tokens(texto) -> tuple[str, ...]:
    """Palabras comparables: sin ", en " (el Excel agrega «, en vivienda» donde la lista usa «: VIVIENDA») y en singular."""
    texto = re.sub(r",\s*en\s+", " ", str(texto), flags=re.IGNORECASE)
    return tuple(t[:-1] if len(t) > 3 and t.endswith("s") else t for t in normalizar_texto(texto).split())


def _tipo_de_coincidencia(texto: tuple[str, ...], etiqueta: tuple[str, ...], truncada: bool) -> str | None:
    n, m = len(etiqueta), len(texto)
    if not truncada:
        if etiqueta == texto:
            return "exacta"
        if 2 <= n < m and texto[:n] == etiqueta:
            return "general"
        if 3 <= m < n and etiqueta[:m] == texto:
            return "texto_abreviado"
        return None
    # etiqueta cortada: la última palabra puede estar incompleta y el resto de la etiqueta se desconoce
    if n <= m and texto[:n - 1] == etiqueta[:-1] and texto[n - 1].startswith(etiqueta[-1]):
        return "etiqueta_cortada"
    if 3 <= m < n and etiqueta[:m - 1] == texto[:-1] and etiqueta[m - 1].startswith(texto[-1]):
        return "texto_abreviado"
    return None


PRIORIDAD_TIPO = {"exacta": 0, "etiqueta_cortada": 1, "general": 2, "texto_abreviado": 3}


def buscar_candidatos(textos, universo: pd.DataFrame, capitulos: str | None = None) -> pd.DataFrame:
    """Por cada texto distinto, el mejor tipo de coincidencia contra el universo y sus líneas candidatas.

    Tipos (de mejor a peor): `exacta`; `etiqueta_cortada` (la lista de REDCap trae la etiqueta cortada y el texto empieza
    igual); `general` (la etiqueta es solo el inicio del texto: el texto agrega detalle, p. ej. el lugar del hecho; se
    propone el código general más largo); `texto_abreviado` (el texto es solo el inicio de la etiqueta); `sin_candidato`.
    `capitulos` limita los códigos por su primera letra (p. ej. "VWXY" para causas externas). `propuesta` solo se llena
    cuando hay una única clave candidata; `candidato_general` es el código general más específico, si existe.
    Es una ayuda para revisar a mano: nada de esto se aplica solo.
    """
    por_inicio: dict[str, list] = {}
    for fila in universo.itertuples():
        if fila.tokens and (not capitulos or fila.clave[0] in capitulos):
            por_inicio.setdefault(fila.tokens[0], []).append(fila)

    resultado = []
    for texto in dict.fromkeys(textos):
        tokens = _tokens(texto)
        encontradas = []
        for u in por_inicio.get(tokens[0] if tokens else "", []):
            tipo = _tipo_de_coincidencia(tokens, u.tokens, u.truncada)
            if tipo:
                encontradas.append((PRIORIDAD_TIPO[tipo], tipo, len(u.tokens), u.con_simbolo, u.clave, u.linea))
        generales = [e for e in encontradas if e[1] == "general"]
        general = max(generales, key=lambda e: (e[2], not e[3]))[5] if generales else ""
        if not encontradas:
            resultado.append((texto, "sin_candidato", 0, "", general, ""))
            continue
        mejor = min(e[0] for e in encontradas)
        elegidas = [e for e in encontradas if e[0] == mejor]
        if elegidas[0][1] == "general":     # solo el código general más específico
            largo = max(e[2] for e in elegidas)
            elegidas = [e for e in elegidas if e[2] == largo]
        por_clave: dict[str, tuple] = {}
        for e in sorted(elegidas, key=lambda e: e[3]):      # la versión sin símbolo primero (7.1)
            por_clave.setdefault(e[4], e)
        lineas = [e[5] for e in por_clave.values()]
        resultado.append((texto, elegidas[0][1], len(lineas), lineas[0] if len(lineas) == 1 else "", general,
                          " || ".join(lineas[:6])))
    return pd.DataFrame(resultado, columns=["texto", "tipo", "n_candidatos", "propuesta", "candidato_general",
                                            "candidatos"])


def candidatos_sin_pareja(df: pd.DataFrame, col: str, col_marca: str, universo: pd.DataFrame,
                          col_campo: str | None = None) -> pd.DataFrame:
    """Candidatos de cada texto distinto sin pareja, agrupados por campo de REDCap (el bloque), para revisión manual.

    Solo se procesan los textos que `mapear_texto_a_cie10` dejó sin pareja (`col_marca` False) y, para cada campo, solo
    los códigos de sus capítulos (CAPITULOS_POR_CAMPO). Sin `col_campo` el campo es el nombre de `col`.
    La columna `decision` queda vacía para el revisor.
    """
    sin = df[df[col_marca].eq(False).fillna(False)]
    campo = sin[col_campo] if col_campo else pd.Series(col, index=sin.index)
    conteo = sin.groupby([campo.fillna("(sin campo)"), sin[col]]).size().rename("n_filas").reset_index()
    conteo.columns = ["campo_redcap", "texto_excel", "n_filas"]
    partes = []
    for nombre, grupo in conteo.groupby("campo_redcap"):
        encontrados = buscar_candidatos(grupo["texto_excel"], universo, CAPITULOS_POR_CAMPO.get(nombre))
        partes.append(grupo.merge(encontrados, left_on="texto_excel", right_on="texto").drop(columns="texto"))
    if not partes:
        return pd.DataFrame(columns=["campo_redcap", "texto_excel", "n_filas", "tipo", "n_candidatos", "propuesta",
                                     "candidato_general", "candidatos", "decision"])
    salida = pd.concat(partes, ignore_index=True)
    salida["decision"] = ""
    orden = salida["tipo"].map({**PRIORIDAD_TIPO, "sin_candidato": 4})
    return (salida.assign(_o=orden).sort_values(["campo_redcap", "_o", "n_filas"], ascending=[True, True, False])
            .drop(columns="_o").reset_index(drop=True))


def cargar_ajustes_excel(ruta: Path = RUTA_AJUSTES_EXCEL) -> dict:
    cfg = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    return {"correcciones_texto": cfg.get("correcciones_texto") or {}, "equivalencias": cfg.get("equivalencias") or {}}


def _corregir(valor, correcciones: dict[str, str]):
    if pd.isna(valor):
        return valor
    texto = str(valor)
    for error, correcta in correcciones.items():
        texto = re.sub(rf"\b{re.escape(error)}\b", correcta, texto, flags=re.IGNORECASE)
    return texto


def mapear_texto_a_cie10(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, col: str, col_marca: str,
                         catalogo: pd.DataFrame | None = None, ajustes: dict | None = None,
                         universo: pd.DataFrame | None = None, col_grupo: str | None = None) -> pd.DataFrame:
    """Reemplaza el texto de `col` por la línea CIE-10 de REDCap cuando hay pareja y agrega `col_marca` (boolean).

    Devuelve las parejas formadas, una fila por (grupo, texto original, resultado, método) con su número de filas, para
    revisarlas; `col_grupo` (p. ej. el campo de REDCap) separa los grupos, y sin él el grupo es `col`.

    Sin pareja se conserva el texto (con su ortografía corregida) en MAYÚSCULAS y la marca queda en False; vacío queda
    vacío. Orden:
    corrección ortográfica -> coincidencia exacta por etiqueta normalizada con el catálogo -> coincidencia exacta con la
    lista completa de REDCap (`universo`, opcional; palabra por palabra, en singular y con «, en lugar» equivalente a
    «: LUGAR»; solo etiquetas completas y una única clave) -> equivalencia revisada a mano. El resto de los parecidos
    (etiqueta cortada, código general) no se aplica: va a `candidatos_sin_pareja`.
    """
    catalogo = cargar_catalogo() if catalogo is None else catalogo
    ajustes = cargar_ajustes_excel() if ajustes is None else ajustes
    base = catalogo if universo is None else universo
    lineas_validas = set(base["linea"])
    equivalencias = {normalizar_texto(k): v for k, v in ajustes["equivalencias"].items()}
    invalidas = sorted(set(equivalencias.values()) - lineas_validas)
    if invalidas:
        raise ValueError(f"Equivalencias hacia líneas que no están en el catálogo: {invalidas}")

    original = df[col].copy()
    informado = original.notna()
    corregido = original.map(lambda v: _corregir(v, ajustes["correcciones_texto"]))
    norm = corregido.map(lambda v: normalizar_texto(v) if pd.notna(v) else None)
    exacta = norm.map(indice_por_texto(catalogo))
    if universo is None:
        completa = pd.Series(False, index=df.index)
    else:
        pendientes = corregido[informado & exacta.isna()].drop_duplicates()
        cand = buscar_candidatos(pendientes, universo)
        unicas = cand[(cand["tipo"] == "exacta") & (cand["n_candidatos"] == 1)]
        extra = corregido.map(dict(zip(unicas["texto"], unicas["propuesta"])))
        completa = exacta.isna() & extra.notna()
        exacta = exacta.fillna(extra)
    manual = exacta.isna() & norm.map(equivalencias).notna()
    linea = exacta.fillna(norm.map(equivalencias))
    mapeado = informado & linea.notna()

    claves_dobles = set(base.groupby("clave")["con_simbolo"].nunique().loc[lambda s: s > 1].index)
    a_sin_simbolo = mapeado & linea.map(dict(zip(base["linea"], base["clave"]))).isin(claves_dobles)

    reporte.registrar_correccion(bloque, col, "error ortografico corregido antes de mapear",
                                 int((informado & (corregido != original)).sum()), "corregido")
    reporte.registrar_correccion(bloque, col, "texto llevado a la linea CIE-10 de REDCap (coincidencia exacta)",
                                 int((mapeado & ~manual & ~completa).sum()), "mapeado")
    if universo is not None:
        reporte.registrar_correccion(bloque, col, "texto llevado a la linea CIE-10 de REDCap (lista completa, "
                                                  "coincidencia exacta)", int(completa.sum()), "mapeado")
    reporte.registrar_correccion(bloque, col, "texto llevado a la linea CIE-10 de REDCap (equivalencia revisada)",
                                 int(manual.sum()), "mapeado")
    reporte.registrar_correccion(bloque, col, "asignado a la version sin simbolo (REDCap tambien la ofrece con * o †)",
                                 int(a_sin_simbolo.sum()), "mapeado")
    reporte.reportar_regla(bloque, f"{col} sin pareja en el catalogo CIE-10 de REDCap (se conserva el texto en mayusculas)",
                           informado, informado & ~mapeado, reporte.llaves(df), [col])

    df[col] = linea.where(mapeado, corregido.astype("string").str.upper()).astype("string")
    df[col_marca] = mapeado.astype("boolean").mask(~informado)
    registrar_estandarizacion(reporte, bloque, col, original, df[col])

    metodo = pd.Series("sin_pareja", index=df.index)
    metodo[mapeado] = "catalogo_exacta"
    metodo[completa & mapeado] = "lista_completa_exacta"
    metodo[manual] = "equivalencia_revisada"
    pares = pd.DataFrame({"grupo": df[col_grupo] if col_grupo else col, "texto_excel": original,
                          "resultado": df[col], "metodo": metodo})[informado]
    return (pares.fillna({"grupo": "(sin campo)"}).groupby(["grupo", "texto_excel", "resultado", "metodo"])
            .size().rename("n_filas").reset_index().sort_values(["grupo", "metodo", "n_filas"],
                                                                ascending=[True, True, False], ignore_index=True))


def unificar_etiquetas_canonicas(df: pd.DataFrame, reporte: ReporteCalidad, bloque: str, columnas,
                                 alternas: dict[str, str] | None = None) -> None:
    """REDCap: reasigna a la etiqueta canónica las líneas con la otra redacción (decisión 7.2). Solo columnas presentes."""
    alternas = redacciones_alternas() if alternas is None else alternas
    for col in columnas:
        if col not in df.columns:
            continue
        cambia = df[col].isin(alternas)
        reporte.registrar_correccion(bloque, col, "linea CIE-10 con dos redacciones llevada a la etiqueta canonica",
                                     int(cambia.sum()), "estandarizado")
        df[col] = df[col].where(~cambia, df[col].map(alternas))
