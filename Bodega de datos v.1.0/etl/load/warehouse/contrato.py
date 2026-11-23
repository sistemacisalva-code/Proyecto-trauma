"""
Contrato de carga de un modelo: de qué tabla y columna del staging sale cada
columna de la bodega, en cada fuente, y cómo se resuelve. El contrato selecciona, renombra y resuelve claves; no
limpia. Hace explícito qué llega a Power BI (minimización de datos) y se puede probar sin leer datos.

Forma del YAML (config/contratos/<modelo>.yaml; el del completo es el ejemplo de referencia):

    modelo: completo
    version: 1
    staging:                                   # grano de cada tabla de staging que usa el contrato, por fuente
      excel:
        informacion_demografica: {grano: atencion}
        signos_vitales: {grano: varias, toma: primera, orden: [fecha_y_hora_de_signos_vitales]}
      redcap: {...}
    tablas:
      dim_tiempo:  {tipo: calendario, columnas: {fecha: {generado: fecha}, es_festivo: {generado: es_festivo,
                    etiquetas: {verdadero: SI, falso: NO}}}}
      dim_cie_10:  {tipo: catalogo, columna: cie_10, sin_mapeo: SIN CODIGO CIE-10}
      dim_caida:   {tipo: dimension, vacio: no_aplica, columnas: {caida: {origen: {excel: t.c, redcap: t.c}}}}
      fact_trauma: {tipo: hecho, filas: {excel: t, redcap: t}, columnas: {
                    paciente_id: {resolucion: dimension, dimension: dim_paciente},
                    fecha_alta_id: {resolucion: calendario, origen: {excel: t.c, redcap: t.c}}}}
      bridge_x:    {tipo: puente, filas: {...}, orden: {excel: [c], redcap: null}, columnas: {
                    secuencia: {resolucion: secuencia}, ...}}
      bridge_cie:  {tipo: puente, por_rol: {<rol>: {filas: {...}, columnas: {
                    cie_10_id: {resolucion: dimension, dimension: dim_cie_10, origen: {...}, mapeado: {...}},
                    texto_origen: {resolucion: texto_sin_mapeo, de: cie_10_id}}}}}

Toda columna con origen lleva las dos fuentes, con null explícito, para que una omisión no pase por "no aplica".
Aquí solo se valida el contrato (estructura, referencias y grano, sin leer datos); lo ejecuta el Loader.
"""
from dataclasses import dataclass
import os

import yaml

FUENTES = ("excel", "redcap")
CLAVE_ATENCION = "trauma_register_id"

TIPOS = ("calendario", "horario", "catalogo", "dimension", "hecho", "puente")
RESOLUCIONES_POR_TIPO = {
    "dimension": ("copia",),
    "hecho": ("copia", "calendario", "horario", "dimension"),
    # texto_sin_mapeo: el texto del origen de otra columna del bloque, solo en las filas que no se mapearon
    "puente": ("copia", "calendario", "horario", "dimension", "secuencia", "texto_sin_mapeo"),
}
CON_ORIGEN = ("copia", "calendario", "horario")
GRANOS = ("atencion", "varias")
VACIOS = ("sin_dato", "no_aplica")

# Atributos que producen los generadores de calendario y horario; cada modelo elige los suyos
ATRIBUTOS_GENERADOS = {
    "calendario": ("fecha", "dia", "mes", "nombre_mes", "trimestre", "anio", "dia_semana", "dia_semana_numero",
                   "es_festivo"),
    "horario": ("hora_larga", "hora", "minuto", "intervalo"),
}
ATRIBUTOS_CON_ETIQUETAS = ("es_festivo",)

# Tipos de Arrow que exige cada uso (la compatibilidad con el tipo de la columna destino la prueba el contrato real)
TIPOS_ARROW = {"calendario": ("timestamp", "date"), "horario": ("timestamp",), "mapeado": ("bool",)}


class ContratoInvalido(ValueError):
    """El contrato no se puede usar: estructura mal formada, referencias rotas u orígenes ausentes del staging."""


@dataclass(frozen=True)
class Contrato:
    modelo: str
    version: int
    staging: dict[str, dict]   # fuente -> {tabla de staging: {"grano", "toma"?, "orden"?}}
    tablas: dict[str, dict]    # tabla destino -> definición (ver la forma en el docstring del módulo)

    def bloques(self) -> list[tuple[str, str, dict]]:
        """
        (nombre, tipo, bloque) de cada unidad que tiene columnas: una por tabla, y una por rol en un puente por_rol
        (nombre "tabla[rol]"). Los catálogos no tienen columnas propias y no aparecen.
        """
        bloques = []
        for tabla, destino in self.tablas.items():
            if "por_rol" in destino:
                bloques += [(f"{tabla}[{rol}]", destino["tipo"], b) for rol, b in destino["por_rol"].items()]
            elif "columnas" in destino:
                bloques.append((tabla, destino["tipo"], destino))
        return bloques

    def columnas_por_tabla(self, fuente: str) -> dict[str, list[str]]:
        """
        Columnas del staging que pide el contrato en una fuente, agrupadas por tabla de staging y sin repetir. Cada
        tabla lleva además la clave de la atención (para unirla) y las columnas de orden de su toma o de su puente.
        """
        columnas: dict[str, set[str]] = {}
        for _, _, bloque in self.bloques():
            filas = (bloque.get("filas") or {}).get(fuente)
            if filas:
                columnas.setdefault(filas, set()).update((bloque.get("orden") or {}).get(fuente) or [])
            for definicion in bloque["columnas"].values():
                for campo in ("origen", "mapeado"):
                    valor = (definicion.get(campo) or {}).get(fuente)
                    if valor:
                        tabla, columna = valor.split(".")
                        columnas.setdefault(tabla, set()).add(columna)
        for tabla, cols in columnas.items():
            cols.add(CLAVE_ATENCION)
            cols.update(self.staging[fuente].get(tabla, {}).get("orden") or [])
        return {tabla: sorted(cols) for tabla, cols in sorted(columnas.items())}

    def validar_contra(self, esquema: dict[str, dict[str, str]], fuente: str) -> None:
        """
        Comprueba que cada columna que pide la fuente exista en el esquema del staging y que las fechas, horas y
        banderas de mapeo tengan el tipo de Arrow que su resolución exige.

        Raises:
            ContratoInvalido: nombra todas las columnas ausentes o de tipo incompatible, no solo la primera.
        """
        errores = [
            f"columna ausente del staging: {tabla}.{columna}"
            for tabla, columnas in self.columnas_por_tabla(fuente).items()
            for columna in columnas
            if columna not in esquema.get(tabla, {})
        ]
        for nombre, _, bloque in self.bloques():
            for columna, definicion in bloque["columnas"].items():
                usos = [("mapeado", definicion.get("mapeado"))]
                if definicion.get("resolucion") in TIPOS_ARROW:
                    usos.append((definicion["resolucion"], definicion.get("origen")))
                for uso, par in usos:
                    valor = (par or {}).get(fuente)
                    if not valor:
                        continue
                    tabla, col = valor.split(".")
                    tipo = esquema.get(tabla, {}).get(col)
                    if tipo is not None and not tipo.startswith(TIPOS_ARROW[uso]):
                        errores.append(f"{nombre}.{columna}: {valor} es {tipo} y el uso '{uso}' exige "
                                       f"{list(TIPOS_ARROW[uso])}")
        if errores:
            raise ContratoInvalido(f"Contrato '{self.modelo}' frente al staging de {fuente}:\n- "
                                   + "\n- ".join(errores))


# ---------------------------------------------------------------------------
# Validación de la estructura (sin leer datos)
# ---------------------------------------------------------------------------

def _es_origen(valor) -> bool:
    return isinstance(valor, str) and valor.count(".") == 1 and all(valor.split("."))


def _es_lista_de_textos(valor) -> bool:
    return isinstance(valor, list) and bool(valor) and all(isinstance(v, str) and v for v in valor)


def _errores_de_par(ruta: str, campo: str, par, valido, descripcion: str) -> list[str]:
    """Un campo con exactamente las dos fuentes, cada una con un valor válido o null."""
    if not isinstance(par, dict) or set(par) != set(FUENTES):
        return [f"{ruta}: '{campo}' debe tener exactamente las fuentes {list(FUENTES)}"]
    return [f"{ruta}: el {campo} de {fuente} debe ser {descripcion}"
            for fuente, valor in par.items() if valor is not None and not valido(valor)]


def _errores_de_staging(staging) -> list[str]:
    if not isinstance(staging, dict) or set(staging) != set(FUENTES):
        return [f"'staging' debe tener exactamente las fuentes {list(FUENTES)}"]
    errores = []
    for fuente, tablas in staging.items():
        if not isinstance(tablas, dict) or not tablas:
            errores.append(f"staging.{fuente} debe ser un mapa no vacío de tablas")
            continue
        for tabla, decl in tablas.items():
            ruta = f"staging.{fuente}.{tabla}"
            if not isinstance(decl, dict) or decl.get("grano") not in GRANOS:
                errores.append(f"{ruta}: 'grano' debe ser uno de {list(GRANOS)}")
                continue
            if "toma" in decl and (decl["toma"] != "primera" or decl["grano"] != "varias"):
                errores.append(f"{ruta}: 'toma: primera' solo se declara en tablas de grano varias")
            if "orden" in decl and ("toma" not in decl or not _es_lista_de_textos(decl["orden"])):
                errores.append(f"{ruta}: 'orden' es una lista de columnas y acompaña a 'toma'")
    return errores


def _errores_de_columna(ruta: str, tipo: str, definicion) -> list[str]:
    if not isinstance(definicion, dict):
        return [f"{ruta}: la definición debe ser un mapa"]
    if tipo in ATRIBUTOS_GENERADOS:
        errores = []
        if definicion.get("generado") not in ATRIBUTOS_GENERADOS[tipo]:
            errores.append(f"{ruta}: 'generado' debe ser uno de {list(ATRIBUTOS_GENERADOS[tipo])}")
        if "etiquetas" in definicion:
            etiquetas = definicion["etiquetas"]
            if (definicion.get("generado") not in ATRIBUTOS_CON_ETIQUETAS or not isinstance(etiquetas, dict)
                    or set(etiquetas) != {"verdadero", "falso"}
                    or not all(isinstance(v, str) for v in etiquetas.values())):
                errores.append(f"{ruta}: 'etiquetas' ({{verdadero, falso}}) solo aplica a "
                               f"{list(ATRIBUTOS_CON_ETIQUETAS)}")
        return errores

    resolucion = definicion.get("resolucion", "copia")
    if resolucion not in RESOLUCIONES_POR_TIPO[tipo]:
        return [f"{ruta}: la resolución {resolucion!r} no se admite en una tabla de tipo {tipo} "
                f"({list(RESOLUCIONES_POR_TIPO[tipo])})"]
    errores = []
    if resolucion in CON_ORIGEN and "origen" not in definicion:
        errores.append(f"{ruta}: la resolución {resolucion!r} necesita 'origen'")
    if resolucion == "secuencia" and "origen" in definicion:
        errores.append(f"{ruta}: la secuencia la numera el Loader y no lleva 'origen'")
    if resolucion == "texto_sin_mapeo" and (not isinstance(definicion.get("de"), str)
                                            or "origen" in definicion or "mapeado" in definicion):
        errores.append(f"{ruta}: 'texto_sin_mapeo' toma el origen y la bandera de otra columna: solo lleva "
                       f"'de: <columna>'")
    if resolucion == "dimension" and not isinstance(definicion.get("dimension"), str):
        errores.append(f"{ruta}: la resolución 'dimension' necesita 'dimension: <tabla>'")
    if "origen" in definicion:
        errores += _errores_de_par(ruta, "origen", definicion["origen"], _es_origen, "'tabla.columna' o null")
    if "mapeado" in definicion:
        if resolucion != "dimension":
            errores.append(f"{ruta}: 'mapeado' solo acompaña a la resolución 'dimension'")
        errores += _errores_de_par(ruta, "mapeado", definicion["mapeado"], _es_origen, "'tabla.columna' o null")
    return errores


def _errores_de_bloque(ruta: str, tipo: str, bloque) -> list[str]:
    columnas = bloque.get("columnas") if isinstance(bloque, dict) else None
    if not isinstance(columnas, dict) or not columnas:
        return [f"{ruta}: 'columnas' debe ser un mapa no vacío"]
    errores = []
    if tipo in ("hecho", "puente"):
        es_tabla = lambda v: isinstance(v, str) and v and "." not in v  # noqa: E731
        errores += _errores_de_par(ruta, "filas", bloque.get("filas"), es_tabla, "una tabla de staging o null")
        if tipo == "hecho" and isinstance(bloque.get("filas"), dict) and None in bloque["filas"].values():
            errores.append(f"{ruta}: el hecho necesita 'filas' en las dos fuentes")
    resoluciones = {c: d.get("resolucion", "copia") for c, d in columnas.items() if isinstance(d, dict)}
    if "orden" in bloque:
        if tipo != "puente":
            errores.append(f"{ruta}: 'orden' de las filas solo se declara en un puente")
        elif "secuencia" not in resoluciones.values():
            errores.append(f"{ruta}: 'orden' solo sirve para numerar la secuencia y el bloque no tiene una")
        else:
            errores += _errores_de_par(ruta, "orden", bloque["orden"], _es_lista_de_textos,
                                       "una lista de columnas o null")
    if tipo == "dimension" and bloque.get("vacio", "sin_dato") not in VACIOS:
        errores.append(f"{ruta}: 'vacio' debe ser uno de {list(VACIOS)}")
    for columna, definicion in columnas.items():
        errores += _errores_de_columna(f"{ruta}.{columna}", tipo, definicion)
        if resoluciones.get(columna) == "texto_sin_mapeo" and isinstance(definicion.get("de"), str):
            fuente_texto = columnas.get(definicion["de"])
            if resoluciones.get(definicion["de"]) != "dimension" or "mapeado" not in fuente_texto:
                errores.append(f"{ruta}.{columna}: 'de' debe ser una columna del bloque con resolución 'dimension' "
                               f"y 'mapeado'")
    return errores


def _errores_de_tabla(tabla: str, destino) -> list[str]:
    tipo = destino.get("tipo") if isinstance(destino, dict) else None
    if tipo not in TIPOS:
        return [f"{tabla}: 'tipo' debe ser uno de {list(TIPOS)}"]
    if tipo == "catalogo":
        errores = [] if isinstance(destino.get("columna"), str) else [f"{tabla}: el catálogo necesita 'columna'"]
        if "sin_mapeo" in destino and not isinstance(destino["sin_mapeo"], str):
            errores.append(f"{tabla}: 'sin_mapeo' es el texto del miembro para lo no mapeado")
        return errores
    if "por_rol" in destino:
        por_rol = destino["por_rol"]
        if tipo != "puente" or not isinstance(por_rol, dict) or not por_rol:
            return [f"{tabla}: 'por_rol' es un mapa no vacío de roles y solo se usa en un puente"]
        if "columnas" in destino or "filas" in destino:
            return [f"{tabla}: con 'por_rol', las filas y columnas se declaran dentro de cada rol"]
        return [e for rol, bloque in por_rol.items() for e in _errores_de_bloque(f"{tabla}[{rol}]", tipo, bloque)]
    return _errores_de_bloque(tabla, tipo, destino)


def _errores_de_estructura(datos, modelo: str) -> list[str]:
    if not isinstance(datos, dict):
        return ["el contrato no es un mapa YAML"]
    errores = []
    if datos.get("modelo") != modelo:
        errores.append(f"'modelo' es {datos.get('modelo')!r} y se esperaba {modelo!r}")
    if not isinstance(datos.get("version"), int):
        errores.append("'version' debe ser un entero")
    errores += _errores_de_staging(datos.get("staging"))
    tablas = datos.get("tablas")
    if not isinstance(tablas, dict) or not tablas:
        return errores + ["'tablas' debe ser un mapa no vacío"]
    for tabla, destino in tablas.items():
        errores += _errores_de_tabla(tabla, destino)
    return errores


# ---------------------------------------------------------------------------
# Validación de referencias y grano (estructura ya válida)
# ---------------------------------------------------------------------------

def _tablas_de(par) -> dict[str, str]:
    """{fuente: tabla de staging} de un par de orígenes 'tabla.columna' (sin los null)."""
    return {fuente: valor.split(".")[0] for fuente, valor in (par or {}).items() if valor}


def _errores_de_referencias(contrato: Contrato) -> list[str]:
    errores = []
    tipos = {tabla: destino["tipo"] for tabla, destino in contrato.tablas.items()}
    if list(tipos.values()).count("hecho") != 1:
        errores.append("el contrato debe tener exactamente una tabla de tipo hecho")

    # Resoluciones que apuntan a otra tabla del contrato
    referencias: dict[str, list[str]] = {}
    for nombre, _, bloque in contrato.bloques():
        for columna, definicion in bloque["columnas"].items():
            ruta, resolucion = f"{nombre}.{columna}", definicion.get("resolucion", "copia")
            if resolucion in ("calendario", "horario") and resolucion not in tipos.values():
                errores.append(f"{ruta}: no hay una tabla de tipo {resolucion} en el contrato")
            if resolucion != "dimension":
                continue
            destino = definicion["dimension"]
            referencias.setdefault(destino, []).append(nombre)
            if tipos.get(destino) not in ("dimension", "catalogo"):
                errores.append(f"{ruta}: '{destino}' no es una dimensión ni un catálogo del contrato")
            elif tipos[destino] == "catalogo" and "origen" not in definicion:
                errores.append(f"{ruta}: un catálogo se busca por valor y necesita 'origen'")
            elif tipos[destino] == "dimension" and "origen" in definicion:
                errores.append(f"{ruta}: una dimensión toma sus atributos de sus columnas, sin 'origen' en la FK")
            if "mapeado" in definicion and "sin_mapeo" not in contrato.tablas.get(destino, {}):
                errores.append(f"{ruta}: 'mapeado' necesita que '{destino}' declare 'sin_mapeo'")
    for tabla, tipo in tipos.items():
        if tipo == "dimension" and len(referencias.get(tabla, [])) != 1:
            errores.append(f"{tabla}: una dimensión la referencia exactamente una columna "
                           f"(referencias: {referencias.get(tabla, [])})")
        if tipo == "catalogo" and not referencias.get(tabla):
            errores.append(f"{tabla}: ningún puente ni hecho usa este catálogo")

    # Grano: cada tabla de staging se une a las filas de su bloque por la atención
    usadas = {fuente: set() for fuente in FUENTES}
    for nombre, tipo, bloque in contrato.bloques():
        if tipo not in ("hecho", "puente"):
            continue
        origenes = [d.get(campo) for d in bloque["columnas"].values() for campo in ("origen", "mapeado")]
        for definicion in bloque["columnas"].values():
            if definicion.get("resolucion") == "dimension" and tipos.get(definicion["dimension"]) == "dimension":
                origenes += [d.get("origen") for d in contrato.tablas[definicion["dimension"]]["columnas"].values()]
        for fuente in FUENTES:
            filas = bloque["filas"][fuente]
            tablas = {t for par in origenes for f, t in _tablas_de(par).items() if f == fuente}
            if filas is None:
                if tablas:
                    errores.append(f"{nombre}: {fuente} no tiene 'filas' pero pide {sorted(tablas)}")
                continue
            declaradas = contrato.staging[fuente]
            for tabla in sorted(tablas | {filas}):
                usadas[fuente].add(tabla)
                decl = declaradas.get(tabla)
                if decl is None:
                    errores.append(f"{nombre}: la tabla {fuente}.{tabla} no está declarada en 'staging'")
                elif tabla == filas:
                    if tipo == "hecho" and decl["grano"] != "atencion":
                        errores.append(f"{nombre}: las filas del hecho ({fuente}.{tabla}) deben ser de grano atencion")
                elif decl["grano"] == "varias" and (tipo == "puente" or "toma" not in decl):
                    errores.append(
                        f"{nombre}: {fuente}.{tabla} tiene varias filas por atención; "
                        + ("un puente solo se une a tablas de grano atencion" if tipo == "puente"
                           else "declare 'toma: primera' para elegir una")
                    )
    for fuente in FUENTES:
        for tabla in sorted(set(contrato.staging[fuente]) - usadas[fuente]):
            errores.append(f"staging.{fuente}.{tabla}: declarada y sin uso en el contrato")
    return errores


def leer_contrato(ruta: str, modelo: str) -> Contrato:
    """
    Lee y valida el contrato de un modelo: estructura, referencias entre tablas y grano del staging.

    Raises:
        ContratoInvalido: si el archivo no existe o el contrato no es válido; lista todos los errores juntos.
    """
    if not os.path.isfile(ruta):
        raise ContratoInvalido(f"No existe el contrato del modelo '{modelo}': '{ruta}'")
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f)

    errores = _errores_de_estructura(datos, modelo)
    if not errores:
        contrato = Contrato(modelo=datos["modelo"], version=datos["version"], staging=datos["staging"],
                            tablas=datos["tablas"])
        errores = _errores_de_referencias(contrato)
    if errores:
        raise ContratoInvalido(f"Contrato '{ruta}' inválido:\n- " + "\n- ".join(errores))
    return contrato
