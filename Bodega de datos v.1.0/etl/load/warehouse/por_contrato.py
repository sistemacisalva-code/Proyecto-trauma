"""
Loader común guiado por el contrato: recorre las tablas del contrato por tipo, en orden de dependencias
(calendario y horario → dimensiones y catálogos → comparación con la bodega → hecho → puentes). Cada modelo solo
declara su nombre y su esquema; todo lo demás sale del YAML y del DDL (reflejado de la base).

Carga incremental por atención: se calcula la huella de cada atención del staging (hecho y puentes) y se
compara con la guardada en la bodega. Las nuevas se insertan, las de huella distinta se actualizan en su lugar (el
hecho con UPDATE, así conservan su fact_id, y sus puentes se reemplazan completos), las iguales no se tocan y las que
ya no están en el staging se borran. `refresco_completo` trata todas como modificadas.

Cuarentena, antes de la transacción:
  - fecha_fuera_de_calendario: la atención con una fecha del hecho fuera del calendario sale completa (todas sus
    filas, de todas las tablas); una fila de puente con su fecha fuera del calendario sale sola.
  - fila_sin_atencion: una fila de una atención que no está en las filas del hecho (la FK del puente la rechazaría).

Conteos por uso para la reconciliación: el hecho con cada tabla que lo alimenta a él o a sus dimensiones, y
cada bloque de puente con su tabla de filas y sus tablas de consulta.
"""
import hashlib
import json
from datetime import date

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.engine import Connection

from etl.load.warehouse.base import BaseLoader, Uso
from etl.load.warehouse.calendario import atributos_del_contrato, generar_calendario, generar_horario, rango_calendario
from etl.load.warehouse.contrato import CLAVE_ATENCION, Contrato
from etl.load.warehouse.cuarentena import COLUMNA_REGLA
from etl.load.warehouse.dimensiones import (
    actualizar, clave_primaria, columnas_de_texto, ids_de_catalogo, ids_de_dimension, insertar, reflejar,
)
from etl.load.warehouse.resolucion import (
    COLUMNA_SECUENCIA, SIN_DATO, combinaciones, filas_de_puente, marco_del_hecho, origen, texto_sin_mapeo,
)
from etl.transform.common.keys import PREFIJOS_FUENTE

# Prefijo de trauma_register_id de cada fuente de la carga (el reemplazo borra solo los de la fuente y no toca la otra)
PREFIJOS = {"excel": PREFIJOS_FUENTE["excel_historico"], "redcap": PREFIJOS_FUENTE["redcap"]}

REGLA_FECHA = "fecha_fuera_de_calendario"
REGLA_HUERFANA = "fila_sin_atencion"

COLUMNA_HUELLA = "huella"   # SHA-256 (hex) de la atención en el hecho
LOTE_DE_LLAVES = 5000       # llaves por sentencia al borrar


def _hecho(contrato: Contrato) -> tuple[str, dict]:
    """Nombre y definición de la única tabla de hechos del contrato (falla si hay más de una o ninguna)."""
    (nombre,) = [t for t, d in contrato.tablas.items() if d["tipo"] == "hecho"]
    return nombre, contrato.tablas[nombre]


def _fechas(serie: pd.Series) -> pd.Series:
    """Convierte la serie a fecha y hora; lo que no se pueda interpretar queda en NaT en vez de lanzar error."""
    return pd.to_datetime(serie, errors="coerce")


def _canonico(valor):
    """
    El valor en una forma que no cambia entre corridas: los vacíos de pandas (None, NaN, NaT, NA) son siempre None, un
    entero que llega como flotante porque su columna tiene vacíos (3.0) es 3, y las fechas van en ISO. Una forma
    inestable no es un riesgo de seguridad sino de falsos cambios: reescribiría atenciones que no cambiaron.
    """
    if valor is None or (not isinstance(valor, (list, tuple, dict)) and pd.isna(valor)):
        return None
    if hasattr(valor, "item"):              # tipos de numpy
        valor = valor.item()
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    if isinstance(valor, date):             # incluye datetime y Timestamp
        return valor.isoformat()
    return valor


def _json(objeto) -> str:
    """Texto canónico de un objeto: claves ordenadas, sin espacios, sin escapar los acentos."""
    return json.dumps(objeto, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _huellas(filas: pd.DataFrame, puentes: list[tuple[str, pd.DataFrame]]) -> dict[str, str]:
    """
    SHA-256 (hex) de cada atención: los valores ya resueltos de su fila del hecho y todas las filas de sus puentes,
    con el nombre de cada columna y sin ningún `fact_id` (no es estable). Las filas de un puente se ordenan por su
    contenido para que no dependan del orden del staging.

    Args:
        filas: el hecho resuelto, con `CLAVE_ATENCION` y una columna por cada una del contrato.
        puentes: [(bloque, filas resueltas)], cada una con `CLAVE_ATENCION` y sus columnas.

    Raises:
        ValueError: si un puente trae filas de una atención que no está en el hecho (no debería ocurrir: la
            cuarentena las aparta antes; fallar es mejor que calcular una huella sobre datos inconsistentes).
    """
    columnas = [c for c in filas.columns if c != CLAVE_ATENCION]
    contenido = {
        clave: {"hecho": dict(zip(columnas, map(_canonico, valores))), "puentes": {}}
        for clave, valores in zip(filas[CLAVE_ATENCION], filas[columnas].itertuples(index=False, name=None))
    }
    for bloque, datos in puentes:
        huerfanas = sorted(set(datos[CLAVE_ATENCION]) - contenido.keys())
        if huerfanas:
            raise ValueError(f"El puente {bloque} tiene filas de atenciones que no están en el hecho: {huerfanas[:5]}"
                             " (la cuarentena fila_sin_atencion debió apartarlas antes de la carga)")
        columnas_puente = [c for c in datos.columns if c != CLAVE_ATENCION]
        for clave, valores in zip(datos[CLAVE_ATENCION],
                                  datos[columnas_puente].itertuples(index=False, name=None)):
            contenido[clave]["puentes"].setdefault(bloque, []).append(
                _json(dict(zip(columnas_puente, map(_canonico, valores)))))
    for atencion in contenido.values():
        atencion["puentes"] = {bloque: sorted(filas_) for bloque, filas_ in atencion["puentes"].items()}
    return {clave: hashlib.sha256(_json(atencion).encode("utf-8")).hexdigest() for clave, atencion in contenido.items()}


class CargaPorContrato(BaseLoader):
    """Loader de un modelo cuyo contrato describe todas sus tablas; las subclases fijan `modelo` y `esquema`."""

    esquema: str = ""

    def __init__(self, *args, hoy: date | None = None, **kwargs):
        """`hoy` fija el fin del calendario (las pruebas lo usan para que el rango sea determinista); por defecto,
        la fecha actual. `_tablas_bd` guarda las tablas reflejadas de la base durante una carga."""
        super().__init__(*args, **kwargs)
        self.rango = rango_calendario(hoy or date.today())
        self._tablas_bd: dict = {}

    # -----------------------------------------------------------------------
    # Cuarentena (paso 6 de run(), sin conexión)
    # -----------------------------------------------------------------------

    def _fuera_del_calendario(self, serie: pd.Series) -> pd.Series:
        """Fechas fuera del rango del calendario; un vacío no está fuera (NaT compara como falso)."""
        dias = _fechas(serie).dt.normalize()
        desde, hasta = self.rango
        return (dias < pd.Timestamp(desde)) | (dias > pd.Timestamp(hasta))

    def separar_cuarentena(self, tablas: dict[str, pd.DataFrame], contrato: Contrato
                           ) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
        """
        Aparta las filas que no se pueden cargar, sin tocar la base de datos (paso 6 de `run()`).

        Returns:
            (tablas que se cargan, cuarentena); ambas con las mismas tablas, y la cuarentena con la columna de la
            regla que apartó cada fila. Una fila que sale aquí no se carga ni se pierde: queda registrada.
        """
        _, hecho = _hecho(contrato)
        filas_hecho = tablas[hecho["filas"][self.fuente]]

        # Atenciones con una fecha del hecho fuera del calendario: salen completas
        fuera = set()
        for definicion in hecho["columnas"].values():
            valor = origen(definicion, self.fuente)
            if definicion.get("resolucion") == "calendario" and valor:
                tabla, columna = valor.split(".")
                df = tablas[tabla]
                fuera |= set(df.loc[self._fuera_del_calendario(df[columna]), CLAVE_ATENCION])
        atenciones = set(filas_hecho[CLAVE_ATENCION]) - fuera

        reglas = {tabla: pd.Series(None, index=df.index, dtype=object) for tabla, df in tablas.items()}
        for tabla, df in tablas.items():
            reglas[tabla] = reglas[tabla].mask(~df[CLAVE_ATENCION].isin(atenciones), REGLA_HUERFANA)
            reglas[tabla] = reglas[tabla].mask(df[CLAVE_ATENCION].isin(fuera), REGLA_FECHA)

        # Filas de puente con su propia fecha fuera del calendario: salen solas
        for _, tipo, bloque in contrato.bloques():
            if tipo != "puente":
                continue
            for definicion in bloque["columnas"].values():
                valor = origen(definicion, self.fuente)
                if definicion.get("resolucion") == "calendario" and valor:
                    tabla, columna = valor.split(".")
                    afuera = self._fuera_del_calendario(tablas[tabla][columna]) & reglas[tabla].isna()
                    reglas[tabla] = reglas[tabla].mask(afuera, REGLA_FECHA)

        quedan, cuarentena = {}, {}
        for tabla, df in tablas.items():
            apartadas = reglas[tabla].notna()
            quedan[tabla] = df[~apartadas]
            cuarentena[tabla] = df[apartadas].assign(**{COLUMNA_REGLA: reglas[tabla][apartadas]})
        return quedan, cuarentena

    # -----------------------------------------------------------------------
    # Carga (paso 7 de run(), dentro de la transacción)
    # -----------------------------------------------------------------------

    def _tabla(self, conexion: Connection, nombre: str):
        """Tabla reflejada de la base, con caché para reflejarla una sola vez por carga."""
        if nombre not in self._tablas_bd:
            self._tablas_bd[nombre] = reflejar(conexion, self.esquema, nombre)
        return self._tablas_bd[nombre]

    def _cargar_tiempo(self, conexion: Connection, contrato: Contrato) -> tuple[dict, dict]:
        """Calendario y horario completos y sus claves: {fecha: id} y {minuto del día: id}."""
        ids_fecha, ids_minuto = {}, {}
        for nombre, destino in contrato.tablas.items():
            if destino["tipo"] not in ("calendario", "horario"):
                continue
            generado = generar_calendario(*self.rango) if destino["tipo"] == "calendario" else generar_horario()
            tabla = self._tabla(conexion, nombre)
            insertar(conexion, tabla, atributos_del_contrato(generado, destino["columnas"]), sin_conflicto=True)
            nombres = {d["generado"]: c for c, d in destino["columnas"].items()}
            pk = clave_primaria(tabla)
            if destino["tipo"] == "calendario":
                consulta = select(tabla.c[pk], tabla.c[nombres["fecha"]])
                ids_fecha = {fecha: clave for clave, fecha in conexion.execute(consulta).all()}
            else:
                consulta = select(tabla.c[pk], tabla.c[nombres["hora"]], tabla.c[nombres["minuto"]])
                ids_minuto = {hora * 60 + minuto: clave for clave, hora, minuto in conexion.execute(consulta).all()}
        return ids_fecha, ids_minuto

    def _resolver(self, conexion: Connection, contrato: Contrato, columna: str, definicion: dict,
                  marco: pd.DataFrame, bloque: dict, tiempo: tuple[dict, dict]) -> pd.Series:
        """Valor de una columna destino para cada fila del marco, según su resolución."""
        resolucion = definicion.get("resolucion", "copia")
        valor = origen(definicion, self.fuente)
        vacia = pd.Series(None, index=marco.index, dtype=object)
        if resolucion == "copia":
            return marco[valor] if valor else vacia
        if resolucion in ("calendario", "horario"):
            if not valor:
                return vacia
            instantes = _fechas(marco[valor])
            if resolucion == "calendario":
                return instantes.dt.date.map(tiempo[0])
            return (instantes.dt.hour * 60 + instantes.dt.minute).map(tiempo[1])   # trunca al minuto (TC-CAR-14)
        if resolucion == "secuencia":
            return marco[COLUMNA_SECUENCIA]
        if resolucion == "texto_sin_mapeo":
            return texto_sin_mapeo(marco, bloque["columnas"][definicion["de"]], self.fuente)

        # resolucion == "dimension"
        nombre = definicion["dimension"]
        destino, tabla = contrato.tablas[nombre], self._tabla(conexion, nombre)
        if destino["tipo"] == "dimension":
            atributos = {c: origen(d, self.fuente) for c, d in destino["columnas"].items()}
            datos = combinaciones(marco, atributos, columnas_de_texto(tabla), destino.get("vacio", "sin_dato"))
            return ids_de_dimension(conexion, tabla, datos)
        # Catálogo: lo no mapeado va al miembro sin_mapeo; un valor vacío en una fila con datos, a 'Sin dato'
        valores = marco[valor].astype(object) if valor else vacia
        bandera = origen(definicion, self.fuente, "mapeado")
        if bandera:
            no_mapeado = valores.notna() & ~marco[bandera].fillna(False).astype(bool)
            valores = valores.where(~no_mapeado, destino["sin_mapeo"])
        valores = valores.where(valores.notna(), SIN_DATO)
        return ids_de_catalogo(conexion, tabla, destino["columna"], valores)

    def cargar(self, conexion: Connection, tablas: dict[str, pd.DataFrame], contrato: Contrato
               ) -> dict[Uso, dict[str, int]]:
        """
        Escribe el modelo en la bodega dentro de la transacción (paso 7 de `run()`): tiempo, y hecho y puentes solo de
        las atenciones nuevas o modificadas. Deja en `self.atenciones` cuántas son nuevas, modificadas,
        sin cambio y eliminadas.

        Returns:
            Conteos por uso {(destino, tabla de staging): {cargadas, otra_toma, sin_valor, duplicado}} que
            `BaseLoader.reconciliar` cruza con las filas leídas y la cuarentena.
        """
        usos: dict[Uso, dict[str, int]] = {}
        self._tablas_bd = {}
        tiempo = self._cargar_tiempo(conexion, contrato)

        # Hecho: una fila por atención con sus dimensiones resueltas
        nombre_hecho, hecho = _hecho(contrato)
        origenes = {origen(d, self.fuente) for d in hecho["columnas"].values()}
        for definicion in hecho["columnas"].values():
            destino = contrato.tablas.get(definicion.get("dimension"), {})
            if destino.get("tipo") == "dimension":
                origenes |= {origen(d, self.fuente) for d in destino["columnas"].values()}
        origenes.discard(None)
        marco, conteos = marco_del_hecho(tablas, hecho["filas"][self.fuente], origenes, contrato.staging[self.fuente])
        usos.update({(nombre_hecho, tabla): conteo for tabla, conteo in conteos.items()})
        filas = pd.DataFrame({
            columna: self._resolver(conexion, contrato, columna, definicion, marco, hecho, tiempo)
            for columna, definicion in hecho["columnas"].items()
        }, index=marco.index)

        # Puentes resueltos con la llave de la atención (el fact_id aún no existe: la huella no lo usa)
        puentes = []   # [(bloque, tabla del puente, filas resueltas)]
        for nombre, tipo, bloque in contrato.bloques():
            if tipo != "puente":
                continue
            armado = filas_de_puente(tablas, bloque, self.fuente, contrato.tablas)
            if armado is None:
                continue
            marco_puente, tabla_filas, conteos = armado
            tabla_puente, _, rol = nombre.partition("[")
            datos = pd.DataFrame({CLAVE_ATENCION: marco_puente[CLAVE_ATENCION]}, index=marco_puente.index)
            if rol:
                datos["rol"] = rol.rstrip("]")
            for columna, definicion in bloque["columnas"].items():
                datos[columna] = self._resolver(conexion, contrato, columna, definicion, marco_puente, bloque, tiempo)

            # Sin secuencia, la clave es el contenido: las repeticiones exactas se unen y se cuentan como duplicado
            duplicado = 0
            if COLUMNA_SECUENCIA not in datos:
                antes = len(datos)
                datos = datos.drop_duplicates()
                duplicado = antes - len(datos)
            puentes.append((nombre, tabla_puente, datos))

            # "cargadas" son las filas del staging representadas en la bodega, estén nuevas o ya cargadas
            usos[(nombre, tabla_filas)] = {"cargadas": len(datos), "duplicado": duplicado, **conteos.pop(tabla_filas)}
            usos.update({(nombre, tabla): conteo for tabla, conteo in conteos.items()})

        # Comparación con la bodega: qué atenciones son nuevas, cambiaron, siguen igual o ya no están
        tabla_hecho = self._tabla(conexion, nombre_hecho)
        if COLUMNA_HUELLA not in tabla_hecho.c:
            raise RuntimeError(f"{tabla_hecho.fullname} no tiene la columna '{COLUMNA_HUELLA}': hay que recrear el "
                               "esquema con el DDL actual (carga incremental)")
        prefijo = f"{PREFIJOS[self.fuente]}-%"
        pk_hecho = clave_primaria(tabla_hecho)
        huellas = _huellas(filas, [(nombre, datos) for nombre, _, datos in puentes])
        guardadas = {clave: (id_hecho, huella) for clave, id_hecho, huella in conexion.execute(
            select(tabla_hecho.c[CLAVE_ATENCION], tabla_hecho.c[pk_hecho], tabla_hecho.c[COLUMNA_HUELLA])
            .where(tabla_hecho.c[CLAVE_ATENCION].like(prefijo))
        ).all()}
        del_staging = set(filas[CLAVE_ATENCION])
        comunes = del_staging & guardadas.keys()
        nuevas, eliminadas = del_staging - guardadas.keys(), guardadas.keys() - del_staging
        # Una fila sin huella (cargada antes de la carga incremental) no es igual a ninguna: cuenta como modificada
        modificadas = comunes if self.refresco_completo else {c for c in comunes if guardadas[c][1] != huellas[c]}
        self.atenciones = {"nuevas": len(nuevas), "modificadas": len(modificadas),
                           "sin_cambio": len(comunes) - len(modificadas), "eliminadas": len(eliminadas)}

        # Eliminadas: se borran (sus puentes se van por ON DELETE CASCADE). Modificadas: el hecho se actualiza en su
        # lugar, así conservan su fact_id, y sus puentes se borran para reinsertarlos completos. Nuevas: se insertan.
        a_borrar = sorted(eliminadas)
        for desde in range(0, len(a_borrar), LOTE_DE_LLAVES):
            conexion.execute(text(f"DELETE FROM {tabla_hecho.fullname} WHERE {CLAVE_ATENCION} = ANY(:claves)"),
                             {"claves": a_borrar[desde:desde + LOTE_DE_LLAVES]})
        con_huella = filas.assign(**{COLUMNA_HUELLA: filas[CLAVE_ATENCION].map(huellas)})
        actualizar(conexion, tabla_hecho, con_huella[con_huella[CLAVE_ATENCION].isin(modificadas)], CLAVE_ATENCION)
        ids_modificadas = sorted(guardadas[c][0] for c in modificadas)
        for nombre_puente in sorted({tabla_puente for _, tabla_puente, _ in puentes}):
            destino = self._tabla(conexion, nombre_puente).fullname
            for desde in range(0, len(ids_modificadas), LOTE_DE_LLAVES):
                conexion.execute(text(f"DELETE FROM {destino} WHERE {pk_hecho} = ANY(:ids)"),
                                 {"ids": ids_modificadas[desde:desde + LOTE_DE_LLAVES]})
        insertar(conexion, tabla_hecho, con_huella[con_huella[CLAVE_ATENCION].isin(nuevas)])
        ids_hecho = dict(conexion.execute(
            select(tabla_hecho.c[CLAVE_ATENCION], tabla_hecho.c[pk_hecho])
            .where(tabla_hecho.c[CLAVE_ATENCION].like(prefijo))
        ).all())

        a_cargar = nuevas | modificadas
        for _, tabla_puente, datos in puentes:
            nuevos = datos[datos[CLAVE_ATENCION].isin(a_cargar)]
            insertar(conexion, self._tabla(conexion, tabla_puente), nuevos.drop(columns=CLAVE_ATENCION).assign(
                **{pk_hecho: nuevos[CLAVE_ATENCION].map(ids_hecho)}))
        return usos
