"""
Staging sintético para las pruebas de la carga: datos inventados con semilla fija, nunca datos reales.

Escribe, para una fuente, una carpeta con la forma del staging real: un Parquet por tabla que pide el contrato, con
los tipos de Arrow del staging (`timestamp[us]`, `int64`, `double`, `bool`, `large_string`), y su `manifiesto.json`.
Las columnas salen del propio contrato (`Contrato.columnas_por_tabla`): si el contrato cambia, el staging sintético
cambia con él.

Todos los valores son inventados (etiquetas como "estado_civil 2", códigos "CIE SINTETICO 1"); no hay ningún dato
de pacientes. Con la misma semilla, el resultado es idéntico.

Casos inyectados, con su atención fija (las pruebas los buscan por `CasosSinteticos.ids`):

| Caso | Atención | Qué tiene | Resultado esperado en la carga |
|---|---|---|---|
| perfil_compartido | 1 y 2 | El mismo perfil demográfico, igual en las dos fuentes | Una sola fila de dim_paciente (TC-CAR-02) |
| vacia | 3 | Solo la clave en las tablas de grano atención; nada en las de varias filas | Dimensiones 'Sin dato' / 'No aplica', medidas y fechas NULL, sin filas de puente |
| tomas | 4 | Varias tomas de signos vitales y de laboratorio (una sin valores, una sin fecha); en el Excel, dos filas en una hoja hija | La primera toma por fecha con algún valor; la misma fila para todas sus columnas |
| hora_con_segundos | 5 | Alta a las 23:59:45 | Hora 23:59 del mismo día (TC-CAR-09) |
| fuera_de_calendario | 6 | Llegada el 2009-06-15, antes del calendario | Cuarentena, la carga continúa (TC-CAR-05) |
| cie_sin_mapeo | 7 | Excel: un diagnóstico mapeado, dos textos distintos sin mapear y uno de ellos repetido; REDCap: el mismo código dos veces | Excel: tres filas, las dos 'SIN CODIGO CIE-10' con su texto_origen, y un duplicado; REDCap: una fila y un duplicado |
| sustancia_repetida | 8 | Excel: la misma sustancia dos veces | Una fila y un duplicado |
| imagenes | 9 | Una imagen sin ningún valor y dos del mismo tipo y región con descripción distinta | La vacía no se carga; las otras con secuencia 1 y 2 |
| orden_procedimientos | 10 | Dos procedimientos guardados en orden inverso a su fecha | Secuencia por fecha, no por el orden del staging |
| lesiones | 11 | Excel: dos lesiones y el mecanismo primario de la atención; REDCap: tres lesiones, una sin mecanismo y una repetida exacta | Excel: el mecanismo copiado a cada lesión; REDCap: tres filas con secuencia 1 a 3, la sin mecanismo apuntando a 'Sin dato' (sin nulos descriptivos) |
| complicacion_sin_mapeo | 12 | Excel: una complicación mapeada, dos textos distintos sin mapear en el mismo lugar y uno de ellos repetido | Tres filas, las dos sin código con su texto_origen, y un duplicado |
| huerfana | 999 | Una fila de procedimientos sin atención en el hecho | Cuarentena (fila_sin_atencion) |

Además, `informacion_demografica` trae `columna_fuera_del_contrato`, que no debe llegar a la bodega (TC-CAR-08).
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import random

import pyarrow as pa
import pyarrow.parquet as pq

from etl.load.warehouse.contrato import CLAVE_ATENCION, Contrato
from etl.transform.common import laboratorio, liquidos, mecanismo, severidad, signos_vitales

SEMILLA = 20261026
PREFIJOS = {"excel": "EX", "redcap": "RC"}
RUN_ID = "2026-10-26T120000"
COLUMNA_FUERA_DEL_CONTRATO = "columna_fuera_del_contrato"

# Tipos del staging real (scripts/esquema_staging.csv); lo que no está aquí es texto
BANDERAS = {"cie10_mapeado", "complicacion_cie10_mapeada"}
ENTEROS = {
    "quinquenio_orden", "dias_de_hospitalizacion", "dias_usados_uci", "duracion_procedimiento_seg",
    "iss", "cabeza", "cara", "torax", "abdomen", "extremidades", "externo",
    "frecuencia_cardiaca", "frecuencia_respiratoria", "presion_arterial_sistolica", "presion_arterial_diastolica",
    "gcs_ocular", "gcs_verbal", "gcs_motora",
}
DECIMALES = {
    "peso", "altura", "temperatura", "saturacion_de_oxigeno", "duracion_de_la_perdida_de_conciencia",
    "pao2", "paco2", "sangre", "altura_en_metros", "scq",
}

# Casos con atención fija; el relleno empieza después
CASOS = {
    "perfil_compartido": (1, 2), "vacia": (3,), "tomas": (4,), "hora_con_segundos": (5,),
    "fuera_de_calendario": (6,), "cie_sin_mapeo": (7,), "sustancia_repetida": (8,), "imagenes": (9,),
    "orden_procedimientos": (10,), "lesiones": (11,), "complicacion_sin_mapeo": (12,), "huerfana": (999,),
}
PRIMERA_DE_RELLENO = 13
PERFIL_COMUN = {
    "quinquenio_edad": "30-34", "quinquenio_orden": 7, "estado_civil": "estado_civil 1", "genero": "genero 1",
    "nacionalidad": "nacionalidad 1", "tipo_de_seguro": "tipo_de_seguro 1", "paciente_asegurado": "paciente_asegurado 1",
}
FECHA_FUERA_DE_CALENDARIO = datetime(2009, 6, 15, 8, 30)
ALTA_CON_SEGUNDOS = datetime(2023, 3, 14, 23, 59, 45)


def _rangos_validos() -> dict[str, tuple[float, float]]:
    """Rango válido de cada columna numérica del staging, tomado de los módulos de la transformación (la misma fuente
    que usa la verificación de la bodega), más los valores de prueba que mantienen la coherencia entre columnas."""
    rangos = {c: e[2] for c, e in signos_vitales.ESPECIFICACION_NUMERICA.items()}
    rangos.update({c: e[2] for c, e in severidad.ESPECIFICACION_SEVERIDAD.items()})
    rangos.update({c: e[1] for c, e in mecanismo.ESPECIFICACION_NUMERICA.items()})
    rangos.update({c: laboratorio.ESPECIFICACION_NUMERICA[c][2] for c in ("pao2", "paco2")})
    rangos["sangre"] = (0, liquidos.LIMITE_DURO_LITROS["sangre"])
    rangos["duracion_de_la_perdida_de_conciencia"] = (0, signos_vitales.LIMITE_PERDIDA_CONCIENCIA_MIN)
    # Presión diastólica menor que la sistólica y días de UCI menores que los de hospitalización, siempre
    rangos.update({"presion_arterial_sistolica": (90, 140), "presion_arterial_diastolica": (50, 89),
                   "dias_de_hospitalizacion": (3, 6), "dias_usados_uci": (0, 2)})
    return rangos


RANGOS_VALIDOS = _rangos_validos()
# Horas después del inicio de la atención de cada fecha del hecho, para que su orden sea siempre llegada, hospitalización, alta
HORAS_DE_LAS_FECHAS = {"fecha_y_hora_de_llegada_del_paciente": 1, "fecha_de_admision": 2, "fecha_y_hora_de_alta": 3}


def tipo_arrow(columna: str) -> pa.DataType:
    if columna in BANDERAS:
        return pa.bool_()
    if columna.startswith("fecha"):
        return pa.timestamp("us")
    if columna in ENTEROS:
        return pa.int64()
    if columna in DECIMALES:
        return pa.float64()
    return pa.large_string()


@dataclass
class CasosSinteticos:
    """Lo que escribió el generador: la carpeta, las atenciones de cada caso y las filas de cada tabla."""
    fuente: str
    carpeta: Path
    ids: dict[str, tuple[str, ...]]            # caso -> trauma_register_id
    atenciones: list[str]                       # filas del hecho (sin la huérfana)
    filas: dict[str, int] = field(default_factory=dict)

    def id(self, caso: str) -> str:
        """La atención de un caso de una sola atención."""
        (unico,) = self.ids[caso]
        return unico


class _Generador:
    """Arma las filas por tabla con los nombres del contrato; los casos sobrescriben filas del relleno."""

    def __init__(self, contrato: Contrato, fuente: str, rng: random.Random):
        self.fuente = fuente
        self.rng = rng
        self.columnas = contrato.columnas_por_tabla(fuente)
        self.granos = {t: d["grano"] for t, d in contrato.staging[fuente].items()}
        # Columnas que ordenan filas (toma o puente): sus valores deben ser distintos dentro de la atención
        self.ordenes = {t: set(d.get("orden") or []) for t, d in contrato.staging[fuente].items()}
        for _, _, bloque in contrato.bloques():
            filas = (bloque.get("filas") or {}).get(fuente)
            if filas:
                self.ordenes.setdefault(filas, set()).update((bloque.get("orden") or {}).get(fuente) or [])
        self.tablas: dict[str, list[dict]] = {t: [] for t in self.columnas}

    def clave(self, n: int) -> str:
        return f"{PREFIJOS[self.fuente]}-{n}"

    def valor(self, tabla: str, columna: str, base: datetime, k: int):
        """Valor inventado según el tipo; k distingue las filas de una misma atención."""
        tipo = tipo_arrow(columna)
        if tipo == pa.bool_():
            return True
        if columna in HORAS_DE_LAS_FECHAS:
            return base + timedelta(hours=HORAS_DE_LAS_FECHAS[columna])
        if tipo == pa.timestamp("us"):
            return base + timedelta(hours=k + 1, minutes=self.rng.randint(0, 59))
        if columna in RANGOS_VALIDOS:
            minimo, maximo = RANGOS_VALIDOS[columna]
            maximo = min(maximo, minimo + 100)   # un tope infinito se acota para el valor inventado
            if tipo == pa.int64():
                return self.rng.randint(math.ceil(minimo), math.floor(maximo))
            return round(self.rng.uniform(minimo, maximo), 1)
        if tipo == pa.int64():
            return self.rng.randint(1, 6)
        if tipo == pa.float64():
            return round(self.rng.uniform(1, 100), 1)
        # Pocas etiquetas por columna, para que las combinaciones de dimensión se repitan; en un puente, una
        # etiqueta distinta por fila, para que no choque con la clave del puente
        return f"{columna} {k + 1 if self.granos[tabla] == 'varias' else self.rng.randint(1, 3)}"

    def fila(self, tabla: str, n: int, base: datetime, k: int = 0, **fijos) -> dict:
        # Una tabla que la fuente no tiene da solo la clave; reemplazar() la descarta (casos de una sola fuente)
        columnas = self.columnas.get(tabla, [])
        fila = {c: self.valor(tabla, c, base, k) for c in columnas if c != CLAVE_ATENCION}
        for columna in self.ordenes.get(tabla, ()):
            if columna in fila:
                fila[columna] = base + timedelta(hours=k + 1)
        fila.update({c: v for c, v in fijos.items() if c in columnas})
        return {CLAVE_ATENCION: self.clave(n), **fila}

    def vacia(self, tabla: str, n: int) -> dict:
        columnas = self.columnas.get(tabla, [])
        return {CLAVE_ATENCION: self.clave(n), **{c: None for c in columnas if c != CLAVE_ATENCION}}

    def atencion(self, n: int, base: datetime, filas_varias: int = 1) -> None:
        """Una atención completa: una fila en cada tabla de grano atención y `filas_varias` en las demás."""
        for tabla in self.columnas:
            repeticiones = 1 if self.granos[tabla] == "atencion" else filas_varias
            self.tablas[tabla] += [self.fila(tabla, n, base, k) for k in range(repeticiones)]

    def reemplazar(self, tabla: str, n: int, filas: list[dict]) -> None:
        """Cambia las filas de una atención en una tabla (si la tabla existe en esta fuente)."""
        if tabla not in self.tablas:
            return
        clave = self.clave(n)
        self.tablas[tabla] = [f for f in self.tablas[tabla] if f[CLAVE_ATENCION] != clave] + filas


def _inyectar_casos(g: _Generador) -> None:
    base = datetime(2022, 5, 10, 8, 0)
    for n in range(1, PRIMERA_DE_RELLENO):
        g.atencion(n, base + timedelta(days=n))

    # perfil_compartido: el mismo perfil en las atenciones 1 y 2 (y en las dos fuentes)
    for n in CASOS["perfil_compartido"]:
        g.reemplazar("informacion_demografica", n, [g.fila("informacion_demografica", n, base, **PERFIL_COMUN)])

    # vacia: solo la clave donde el grano es atención; ninguna fila donde hay varias
    (n,) = CASOS["vacia"]
    for tabla, grano in g.granos.items():
        if tabla in g.tablas:
            g.reemplazar(tabla, n, [g.vacia(tabla, n)] if grano == "atencion" else [])
    # Vacía de atributos, pero con su fecha de llegada: es un campo crítico (QR-NUL-01) y sin ella no habría hecho
    g.reemplazar("informacion_demografica", n, [{**g.vacia("informacion_demografica", n),
                                                 "fecha_y_hora_de_llegada_del_paciente": base + timedelta(days=n, hours=1)}])

    # tomas: signos vitales con una toma más temprana sin valores (se salta), la esperada, una sin fecha y una
    # posterior; laboratorio con una primera toma que solo trae PaCO2 (alimenta las dos columnas)
    (n,) = CASOS["tomas"]
    t = base + timedelta(days=n)
    vacia_temprana = {**g.vacia("signos_vitales", n), "fecha_y_hora_de_signos_vitales": t}
    g.reemplazar("signos_vitales", n, [
        g.fila("signos_vitales", n, t, 3, fecha_y_hora_de_signos_vitales=t + timedelta(hours=3), frecuencia_cardiaca=110),
        vacia_temprana,
        g.fila("signos_vitales", n, t, 1, fecha_y_hora_de_signos_vitales=t + timedelta(hours=1), frecuencia_cardiaca=90),
        g.fila("signos_vitales", n, t, 2, fecha_y_hora_de_signos_vitales=None, frecuencia_cardiaca=70),
    ])
    g.reemplazar("laboratorio", n, [
        g.fila("laboratorio", n, t, 2, fecha_y_hora_de_laboratorio=t + timedelta(hours=2), pao2=95.0, paco2=40.0),
        {**g.vacia("laboratorio", n), "fecha_y_hora_de_laboratorio": t + timedelta(hours=1), "paco2": 38.0},
    ])
    # Hoja hija del Excel sin orden: gana la primera fila del staging
    g.reemplazar("quemaduras", n, [g.fila("quemaduras", n, t, 0, quemadura="quemadura primera"),
                                   g.fila("quemaduras", n, t, 1, quemadura="quemadura segunda")])

    # hora_con_segundos
    (n,) = CASOS["hora_con_segundos"]
    g.reemplazar("hospitalizacion", n, [g.fila("hospitalizacion", n, base + timedelta(days=n),
                                               fecha_y_hora_de_alta=ALTA_CON_SEGUNDOS)])

    # fuera_de_calendario: la llegada (fecha de admisión del hecho) antes de 2011
    (n,) = CASOS["fuera_de_calendario"]
    g.reemplazar("informacion_demografica", n, [g.fila(
        "informacion_demografica", n, base, fecha_y_hora_de_llegada_del_paciente=FECHA_FUERA_DE_CALENDARIO)])

    # cie_sin_mapeo, rol diagnóstico. Excel: uno mapeado, dos textos sin pareja y uno de ellos repetido;
    # REDCap (sin bandera): el mismo código dos veces
    (n,) = CASOS["cie_sin_mapeo"]
    tabla = "cie_10_diagnostico_definitivo"
    sin_pareja = g.fila(tabla, n, base, 1, cie_10_diagnostico_definitivo="texto sin pareja 1", cie10_mapeado=False)
    g.reemplazar(tabla, n, [
        g.fila(tabla, n, base, 0, cie_10_diagnostico_definitivo="CIE SINTETICO 1", cie10_mapeado=True),
        sin_pareja,
        g.fila(tabla, n, base, 2, cie_10_diagnostico_definitivo="texto sin pareja 2", cie10_mapeado=False),
        dict(sin_pareja),
    ])
    tabla = "cie_10_diagnosticos"
    g.reemplazar(tabla, n, [g.fila(tabla, n, base, k, cie_10_diagnostico_definitivo="CIE SINTETICO 1")
                            for k in range(2)])

    # sustancia_repetida (Excel; en REDCap la sustancia es una por atención)
    (n,) = CASOS["sustancia_repetida"]
    g.reemplazar("abuso_sustancias", n, [g.fila("abuso_sustancias", n, base, k, abuso_de_drogas="sustancia 1")
                                         for k in range(2)])

    # imagenes: una sin ningún valor y dos del mismo tipo y región
    (n,) = CASOS["imagenes"]
    misma = {"tipo_de_imagen": "tipo_de_imagen 1", "parte_del_cuerpo_imagenes": "parte_del_cuerpo_imagenes 1"}
    g.reemplazar("imagenes", n, [
        g.vacia("imagenes", n),
        g.fila("imagenes", n, base, 0, **misma, descripcion_imagen="descripcion 1"),
        g.fila("imagenes", n, base, 1, **misma, descripcion_imagen="descripcion 2"),
    ])

    # orden_procedimientos: el posterior primero en el staging
    (n,) = CASOS["orden_procedimientos"]
    t = base + timedelta(days=n)
    g.reemplazar("procedimientos", n, [
        g.fila("procedimientos", n, t, 1, procedimientos="procedimiento tarde",
               fecha_y_hora_de_procedimiento=t + timedelta(hours=5)),
        g.fila("procedimientos", n, t, 0, procedimientos="procedimiento temprano",
               fecha_y_hora_de_procedimiento=t + timedelta(hours=2)),
    ])

    # lesiones: Excel con mecanismo por atención; REDCap con mecanismo por lesión, uno vacío, y una lesión repetida
    # exacta (son dos lesiones: las dos se cargan)
    (n,) = CASOS["lesiones"]
    if g.fuente == "excel":
        g.reemplazar("examen_fisico", n, [g.fila("examen_fisico", n, base, mecanismo_primario="mecanismo_primario 1")])
        g.reemplazar("tipo_violencia", n, [g.fila("tipo_violencia", n, base, k) for k in range(2)])
    else:
        lesion = g.fila("examen_fisico", n, base, 0)
        g.reemplazar("examen_fisico", n, [lesion, g.fila("examen_fisico", n, base, 1, mecanismo_primario=None),
                                          dict(lesion)])

    # complicacion_sin_mapeo (Excel): una mapeada, dos textos sin pareja en el mismo lugar y uno de ellos repetido
    (n,) = CASOS["complicacion_sin_mapeo"]
    tabla = "complicaciones_hospitalizacion"

    def complicacion(k, texto, mapeada):
        return g.fila(tabla, n, base, k, cie_10_complicaciones_de_hospitalizacion=texto,
                      complicacion_cie10_mapeada=mapeada, lugar_de_complicacion="lugar_de_complicacion 1")
    sin_pareja = complicacion(1, "complicacion sin pareja 1", False)
    g.reemplazar(tabla, n, [complicacion(0, "CIE SINTETICO 2", True), sin_pareja,
                            complicacion(2, "complicacion sin pareja 2", False), dict(sin_pareja)])

    # huerfana: un procedimiento de una atención que no está en el hecho
    (n,) = CASOS["huerfana"]
    g.tablas["procedimientos"].append(g.fila("procedimientos", n, base))


def _escribir_tabla(ruta: Path, columnas: list[str], filas: list[dict]) -> None:
    arreglos = [pa.array([f.get(c) for f in filas], type=tipo_arrow(c)) for c in columnas]
    pq.write_table(pa.Table.from_arrays(arreglos, names=columnas), ruta, compression="snappy")


def generar_staging(destino: Path, fuente: str, contrato: Contrato, atenciones_relleno: int = 8,
                    semilla: int = SEMILLA) -> CasosSinteticos:
    """
    Escribe el staging sintético de una fuente en `destino` (la carpeta se crea) y devuelve sus casos.

    Args:
        atenciones_relleno: atenciones sin defectos, después de los casos (volumen y variedad de combinaciones).
    """
    if fuente not in PREFIJOS:
        raise ValueError(f"Fuente desconocida: '{fuente}'")
    g = _Generador(contrato, fuente, random.Random(semilla))
    _inyectar_casos(g)
    for n in range(PRIMERA_DE_RELLENO, PRIMERA_DE_RELLENO + atenciones_relleno):
        base = datetime(2015, 1, 1, 0, 0) + timedelta(days=g.rng.randint(0, 3000), minutes=g.rng.randint(0, 1439))
        g.atencion(n, base, filas_varias=g.rng.randint(1, 2))

    destino.mkdir(parents=True, exist_ok=True)
    filas = {}
    for tabla, columnas in g.columnas.items():
        if tabla == "informacion_demografica":
            columnas = [*columnas, COLUMNA_FUERA_DEL_CONTRATO]
            for f in g.tablas[tabla]:
                f[COLUMNA_FUERA_DEL_CONTRATO] = "no debe llegar a la bodega"
        _escribir_tabla(destino / f"{tabla}.parquet", columnas, g.tablas[tabla])
        filas[tabla] = len(g.tablas[tabla])

    manifiesto = {"run_id": RUN_ID, "source_type": fuente, "transformed_at": "2026-10-26T12:00:00+00:00",
                  "elapsed_seconds": 0.0, "rows": filas, "procedencia": {"sintetico": True, "semilla": semilla}}
    (destino / "manifiesto.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")

    atenciones = sorted({f[CLAVE_ATENCION] for f in g.tablas["informacion_demografica"]})
    return CasosSinteticos(fuente=fuente, carpeta=destino, atenciones=atenciones, filas=filas,
                           ids={caso: tuple(g.clave(n) for n in ns) for caso, ns in CASOS.items()})
