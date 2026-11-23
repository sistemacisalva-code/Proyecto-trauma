"""
QR-DOM-04: cada atributo categórico de las dimensiones toma solo valores de una lista permitida (listas en
config/valores_permitidos.yaml; plantilla en config/valores_permitidos.example.yaml). Los catálogos de los puentes (`dim_mecanismo_primario`,
`dim_parte_cuerpo_lesion`, etc.) quedan fuera por ahora.

Las listas no viven en el código: se leen de `config/valores_permitidos.yaml`, que define quien conoce el dominio clínico
(plantilla: `config/valores_permitidos.example.yaml`). Así el verificador solo ve la regla y nunca los valores. Igual que
las demás verificaciones, devuelve solo conteos (`Resultado`).
"""
from pathlib import Path

import yaml
from sqlalchemy import text
from sqlalchemy.engine import Connection

from etl.load.warehouse.contrato import Contrato
from etl.load.warehouse.resolucion import NO_APLICA, SIN_DATO
from etl.quality.comun import Resultado, columna_de, esquema_de, tabla_de

# Los miembros por defecto los pone la carga cuando el staging viene vacío; no son valores del dominio
MIEMBROS_POR_DEFECTO = (SIN_DATO, NO_APLICA)


class ValoresPermitidosInvalidos(ValueError):
    """El archivo de valores permitidos no es válido (no se evalúa nada hasta corregirlo)."""


def leer_permitidos(ruta: str | Path, contrato: Contrato) -> dict[str, dict[str, list[str]]]:
    """
    Lee y valida `{dimensión: {atributo: [valores]}}`. Falla con todos los problemas juntos si una dimensión o un atributo no
    existen en el contrato, si una lista está vacía o si un valor no es texto. Un valor sin comillas como `No`, `Si` o
    `10` lo interpreta YAML como booleano o número y cambiaría el dominio sin avisar: por eso se exige texto.
    """
    contenido = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    problemas = []
    if not isinstance(contenido, dict):
        raise ValoresPermitidosInvalidos("el archivo debe ser un mapa {dimensión: {atributo: [valores]}}")
    permitidos: dict[str, dict[str, list[str]]] = {}
    for dimension, atributos in contenido.items():
        definicion = contrato.tablas.get(dimension)
        if not definicion or definicion["tipo"] != "dimension":
            problemas.append(f"«{dimension}» no es una dimensión del contrato")
            continue
        if not isinstance(atributos, dict):
            problemas.append(f"«{dimension}» debe traer un mapa {{atributo: [valores]}}")
            continue
        for atributo, valores in atributos.items():
            donde = f"{dimension}.{atributo}"
            if atributo not in definicion["columnas"]:
                problemas.append(f"«{donde}» no es un atributo de la dimensión")
            elif not isinstance(valores, list) or not valores:
                problemas.append(f"«{donde}» debe ser una lista con al menos un valor")
            elif any(not isinstance(v, str) or not v.strip() for v in valores):
                problemas.append(f"«{donde}» tiene valores que no son texto (ponlos entre comillas: \"No\", \"10\")")
            else:
                permitidos.setdefault(dimension, {})[atributo] = list(valores)
    if problemas:
        raise ValoresPermitidosInvalidos("; ".join(problemas))
    return permitidos


def verificar_valores_permitidos(conexion: Connection, contrato: Contrato,
                                 permitidos: dict[str, dict[str, list[str]]]) -> list[Resultado]:
    """
    QR-DOM-04 (advierte): por atributo con lista, cuántos miembros de la dimensión tienen un valor fuera de ella.
    Evaluados: los miembros con valor (se excluyen los vacíos y los miembros por defecto 'Sin dato' y 'No aplica').
    Se compara como texto, para cubrir atributos numéricos. Solo cuenta; no devuelve los valores.
    """
    esquema = esquema_de(contrato)
    resultados = []
    for dimension, atributos in permitidos.items():
        tabla = tabla_de(conexion, esquema, dimension)
        for atributo, valores in atributos.items():
            propio = f"{columna_de(conexion, atributo)}::text"
            con_valor = f"{propio} IS NOT NULL AND {propio} <> ALL(:defecto)"
            evaluadas, fuera = conexion.execute(text(
                f"SELECT count(*) FILTER (WHERE {con_valor}), "
                f"count(*) FILTER (WHERE {con_valor} AND {propio} <> ALL(:permitidos)) FROM {tabla}"
            ), {"defecto": list(MIEMBROS_POR_DEFECTO), "permitidos": valores}).one()
            resultados.append(Resultado("QR-DOM-04", f"{dimension}.{atributo}: valores fuera de la lista",
                                        evaluadas, fuera))
    return resultados
