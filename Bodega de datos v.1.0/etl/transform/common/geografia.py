"""Estandarizacion de municipios colombianos escritos a mano (Excel historico).

Las reglas viven en config/estandar_municipios.yaml. Un valor solo se convierte en municipio si esta en el catalogo;
los departamentos escritos en lugar del municipio, los valores sin informacion y los no identificables quedan vacios.
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd
import yaml

# Dominio de la columna departamento: 32 departamentos y el Distrito Capital, con el nombre oficial (DANE)
DEPARTAMENTOS = (
    "Amazonas", "Antioquia", "Arauca", "Atlántico", "Bogotá, D.C.", "Bolívar", "Boyacá", "Caldas", "Caquetá",
    "Casanare", "Cauca", "Cesar", "Chocó", "Córdoba", "Cundinamarca", "Guainía", "Guaviare", "Huila", "La Guajira",
    "Magdalena", "Meta", "Nariño", "Norte de Santander", "Putumayo", "Quindío", "Risaralda",
    "San Andrés, Providencia y Santa Catalina", "Santander", "Sucre", "Tolima", "Valle del Cauca", "Vaupés",
    "Vichada",
)

RUTA_CATALOGO = Path(__file__).resolve().parents[3] / "config" / "estandar_municipios.yaml"


def normalizar_texto(valor) -> str:
    """Minusculas, sin tildes ni signos y con un solo espacio entre palabras."""
    texto = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()


def cargar_catalogo(ruta: Path = RUTA_CATALOGO) -> dict[str, dict]:
    """Devuelve {variante_normalizada: {municipio, departamento, tipo, confianza, nota}}."""
    cfg = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    cat: dict[str, dict] = {}

    def agregar(variante, **datos):
        clave = normalizar_texto(variante)
        if clave in cat and cat[clave] != datos:
            raise ValueError(f"Variante repetida con destinos distintos: {variante!r}")
        cat[clave] = datos

    for e in cfg["municipios"]:
        if e["departamento"] not in DEPARTAMENTOS + ("Sin determinar",):
            raise ValueError(f"Departamento fuera del dominio: {e['departamento']!r} ({e['municipio']})")
        for v in e["variantes"]:
            agregar(v, municipio=e["municipio"], departamento=e["departamento"], tipo="municipio",
                    confianza=e.get("confianza", "alta"), nota=e.get("nota", ""))
    sm = cfg["sin_municipio"]
    for d in sm["departamentos"]:
        for v in d["variantes"]:
            agregar(v, municipio="", departamento=d["valor"], tipo="solo_departamento", confianza="alta",
                    nota="El valor es un departamento; no se puede inferir el municipio")
    for v in sm["sin_informacion"]:
        agregar(v, municipio="", departamento="", tipo="sin_informacion", confianza="alta", nota="")
    for v in sm["no_identificables"]:
        agregar(v, municipio="", departamento="", tipo="no_identificable", confianza="baja",
                nota="No se puede identificar el lugar; confirmar con el hospital")
    return cat


def clasificar_municipios(serie: pd.Series, catalogo: dict[str, dict] | None = None) -> pd.DataFrame:
    """Clasifica cada valor de `serie`: columnas municipio (MAYUSCULAS o NA), tipo y confianza.

    Los nulos conservan tipo 'nulo'. Un valor fuera del catalogo queda con tipo 'sin_clasificar' y municipio NA.
    """
    catalogo = catalogo or cargar_catalogo()
    sin_clasificar = {"municipio": "", "tipo": "sin_clasificar", "confianza": ""}

    def resolver(valor):
        if pd.isna(valor):
            return {"municipio": "", "tipo": "nulo", "confianza": ""}
        clave = normalizar_texto(valor)
        if clave == "":
            return {"municipio": "", "tipo": "sin_informacion", "confianza": "alta"}
        return catalogo.get(clave, sin_clasificar)

    res = pd.DataFrame([resolver(v) for v in serie], index=serie.index)
    res["municipio"] = res["municipio"].str.upper().replace("", pd.NA)
    return res[["municipio", "tipo", "confianza"]]


def estandarizar_municipios(serie: pd.Series, catalogo: dict[str, dict] | None = None) -> pd.Series:
    """Municipio en MAYUSCULAS (con tildes); NA para departamentos, sin informacion y no identificables."""
    return clasificar_municipios(serie, catalogo)["municipio"].rename(serie.name)


def cargar_catalogo_departamentos(ruta: Path = RUTA_CATALOGO) -> dict[str, str]:
    """Devuelve {variante_normalizada: nombre oficial del departamento}."""
    cfg = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    fuera = [d["nombre"] for d in cfg["departamentos"] if d["nombre"] not in DEPARTAMENTOS]
    if fuera:
        raise ValueError(f"Departamentos fuera del dominio de demografia.DEPARTAMENTOS: {fuera}")
    return {normalizar_texto(v): d["nombre"] for d in cfg["departamentos"] for v in d["variantes"]}


def clasificar_departamentos(serie: pd.Series, catalogo: dict[str, str] | None = None) -> pd.DataFrame:
    """Clasifica cada valor de `serie`: columnas departamento (MAYUSCULAS o NA) y tipo.

    tipo: departamento | nulo | sin_clasificar (fuera del catalogo: otro pais, texto libre). Los dos ultimos dan NA.
    """
    catalogo = catalogo or cargar_catalogo_departamentos()
    nombres, tipos = [], []
    for valor in serie:
        if pd.isna(valor) or normalizar_texto(valor) == "":
            nombres.append(pd.NA)
            tipos.append("nulo")
        elif normalizar_texto(valor) in catalogo:
            nombres.append(catalogo[normalizar_texto(valor)].upper())
            tipos.append("departamento")
        else:
            nombres.append(pd.NA)
            tipos.append("sin_clasificar")
    return pd.DataFrame({"departamento": nombres, "tipo": tipos}, index=serie.index)


def departamento_por_municipio(ruta: Path = RUTA_CATALOGO) -> dict[str, str]:
    """{MUNICIPIO EN MAYUSCULAS: DEPARTAMENTO EN MAYUSCULAS} solo para entradas de confianza alta y con departamento.

    Las entradas con departamento supuesto (confianza media/baja) o 'Sin determinar' no se usan para inferir.
    """
    cfg = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    mapa: dict[str, str] = {}
    for e in cfg["municipios"]:
        if e.get("confianza", "alta") != "alta" or e["departamento"] == "Sin determinar":
            continue
        muni, depto = e["municipio"].upper(), e["departamento"].upper()
        if mapa.setdefault(muni, depto) != depto:
            raise ValueError(f"Municipio con dos departamentos en el catalogo: {muni}")
    return mapa


def completar_departamento(municipio: pd.Series, departamento: pd.Series, confianza: pd.Series,
                           mapa: dict[str, str] | None = None) -> tuple[pd.Series, pd.Series]:
    """Rellena departamento vacio a partir del municipio, solo si el municipio se leyo con confianza alta.

    Nunca sobrescribe un departamento ya informado. Devuelve (departamento completo, mascara de filas rellenadas).
    """
    mapa = mapa or departamento_por_municipio()
    inferido = municipio.map(mapa)
    llenar = departamento.isna() & municipio.notna() & (confianza == "alta") & inferido.notna()
    return departamento.mask(llenar, inferido), llenar

