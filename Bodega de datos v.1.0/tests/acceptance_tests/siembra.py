"""
Siembra del staging sintético para TC-ACE-01, 08, 09, 12 y 15 (indicadores derivados).

El generador de `tests/fixtures/staging_sintetico.py` llena todas las columnas de cada atención con valores válidos, así que
ninguna atención carece de mecanismo, ninguna presión es crítica y todo `sangre` es mayor que 0: los indicadores de abajo
darían un resultado igual con o sin su lógica. Este módulo reescribe, solo en las atenciones de relleno de una carpeta de
staging sintético (ningún dato real), los valores que esos indicadores necesitan para distinguir un caso de otro: mecanismos
presentes o ausentes, GCS, presión sistólica y frecuencia cardiaca en los bordes, sangre en 0 y vacía, ISS en los bordes de
cada rango, las etiquetas de muerte y la fecha de alta (estancias de distinta duración, con la hora del alta en los dos
bordes del día y atenciones sin alta).

La siembra solo escribe valores; el valor esperado de cada indicador lo calcula la prueba leyendo el staging ya sembrado,
así que nada de lo sembrado se compara contra sí mismo. Las pruebas verifican, además, que la siembra produjo la variedad
que necesitan (ver `test_indicadores_derivados.py`).
"""
from datetime import timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from etl.load.warehouse.contrato import CLAVE_ATENCION
from tests.acceptance_tests.ayudas import LLEGADA
from tests.fixtures.staging_sintetico import PERFIL_COMUN, PRIMERA_DE_RELLENO

MUERTE = ("Fallece (Morgue)", "Murió antes de la llegada", "Murió en el Departamento de emergencias")
# Disposición de cada atención sembrada: tres muertes, destinos que no son muerte y una sin disposición registrada
DISPOSICIONES = (MUERTE[0], "Alta a domicilio", "Hospitalización", MUERTE[1], None, "Alta a domicilio", "Remisión",
                 MUERTE[2], "Hospitalización", "Alta a domicilio")
# ISS en los bordes de cada rango (1-8, 9-15, 16-24, 25 o más) y una atención sin ISS
ISS = (None, 4, 9, 16, 25, 40, 8, 15, 24)
SANGRE = (None, 0.0, 0.5, 1.5, 2.0)
# Días enteros entre la fecha de llegada y la de alta (None = atención sin alta). La hora del alta alterna entre dos bordes
# del día: a las 23:50 y a las 00:10, así los días enteros difieren de las horas transcurridas (una estancia de 1 día puede
# durar 40 minutos, y una de 0 días, casi 24 horas)
ESTANCIAS = (0, 1, 3, None, 7, 0, 30, 2, 1, 14)
HORAS_DE_ALTA = ((23, 50), (0, 10))

# (GCS ocular, verbal, motor, presión sistólica, frecuencia cardiaca): cada fila cae distinto en los tres criterios
#   gcs < 9 | sistólica < 90 | frecuencia / sistólica > 0,9, con el vacío como indeterminado y sin dividir por cero
SIGNOS = (
    (1, 1, 1, 80, 100),      # GCS 3 crítico, sistólica crítica, índice 1,25
    (4, 2, 3, 89, 70),       # GCS 9 (borde, no), sistólica crítica, índice 0,79
    (2, 2, 3, 90, 91),       # GCS 7 crítico, sistólica 90 (borde, no), índice 1,01
    (3, None, 4, 100, 91),   # GCS indeterminado (un componente vacío), índice 0,91
    (4, 5, 6, 0, 80),        # presión sistólica 0: crítica y sin índice (no se divide por cero)
    (4, 5, 6, None, 80),     # presión sistólica vacía: sin criterio ni índice
    (4, 5, 6, 100, 90),      # índice 0,9 (borde, no)
    (4, 5, 6, 120, None),    # frecuencia cardiaca vacía: sin índice
)

# Mecanismos presentes en cada atención sembrada (ninguno, uno solo y dos a la vez)
MECANISMOS = ("caida", "quemadura", "accidente", "arma_fuego", "arma_blanca")
PATRONES_MECANISMO = ((), ("caida",), ("quemadura",), ("accidente",), ("arma_fuego",), ("caida", "arma_blanca"),
                      ("accidente", "quemadura"))

_MECANISMO_DE_LESION = "mecanismo_de_lesion"
# Columnas del staging de cada mecanismo, por fuente: [(tabla, [columnas])]
COLUMNAS_DEL_MECANISMO = {
    "caida": {f: [(_MECANISMO_DE_LESION, ["lesiones_de_caidas", "tipo_de_superficie"])] for f in ("excel", "redcap")},
    "quemadura": {
        "excel": [("quemaduras", ["quemadura", "grado_de_quemadura"])],
        "redcap": [(_MECANISMO_DE_LESION, ["quemadura", "grado_de_quemadura"])]},
    "accidente": {
        "excel": [(_MECANISMO_DE_LESION, ["velocidad_de_colision", "tipo_de_vehiculo", "ocupante"]),
                  ("colisiones", ["tipo_de_colision"])],
        "redcap": [(_MECANISMO_DE_LESION,
                    ["velocidad_de_colision", "tipo_de_vehiculo", "ocupante", "tipo_de_colision"])]},
    "arma_fuego": {
        "excel": [("arma_fuego", ["lesiones_por_arma_de_fuego"])],
        "redcap": [(_MECANISMO_DE_LESION, ["lesiones_por_arma_de_fuego"])]},
    "arma_blanca": {
        "excel": [("arma_blanca", ["lesiones_por_armas_blancas_laceraciones"])],
        "redcap": [(_MECANISMO_DE_LESION, ["lesiones_por_armas_blancas_laceraciones"])]},
}
TABLA_DE_DISPOSICION = {"excel": "atencion_urgencias", "redcap": "hospitalizacion"}


def _editar(carpeta: Path, tabla: str, cambios: dict[str, dict]) -> None:
    """Reescribe el Parquet de una tabla con los cambios {llave de atención: {columna: valor}}, conservando su esquema."""
    ruta = carpeta / f"{tabla}.parquet"
    original = pq.read_table(ruta)
    filas = original.to_pylist()
    for fila in filas:
        fila.update({c: v for c, v in cambios.get(fila[CLAVE_ATENCION], {}).items() if c in fila})
    pq.write_table(pa.Table.from_pylist(filas, schema=original.schema), ruta, compression="snappy")


def atenciones_de_relleno(carpeta: str | Path) -> list[str]:
    """Llaves de las atenciones de relleno (sin los casos fijos ni la huérfana), en orden numérico: las que se siembran."""
    llaves = pq.read_table(Path(carpeta) / "informacion_demografica.parquet", columns=[CLAVE_ATENCION]).to_pylist()
    numero = lambda llave: int(llave.split("-")[1])
    return sorted({f[CLAVE_ATENCION] for f in llaves if PRIMERA_DE_RELLENO <= numero(f[CLAVE_ATENCION]) < 999}, key=numero)


def _orden_del_quinquenio(etiqueta: str) -> int:
    """
    El orden que corresponde a una etiqueta de quinquenio: depende solo de la etiqueta, como en los datos reales. El
    generador sortea etiqueta y orden por separado, y con muchas atenciones dos con la misma etiqueta y distinto orden
    chocan en `uq_dim_paciente`, que no incluye el orden: la carga rechaza esa combinación.
    """
    if etiqueta == PERFIL_COMUN["quinquenio_edad"]:
        return PERFIL_COMUN["quinquenio_orden"]
    prefijo = "quinquenio_edad "
    if etiqueta.startswith(prefijo):
        return int(etiqueta.removeprefix(prefijo))
    raise ValueError(f"Etiqueta de quinquenio desconocida en el staging sintético: {etiqueta!r}")


def sembrar(carpeta: str | Path, fuente: str) -> list[str]:
    """
    Siembra el staging sintético de una fuente (carpeta ya generada) y devuelve las llaves de las atenciones sembradas.

    Cada indicador recorre su propia lista con un período distinto (7, 8, 9, 10 y 5), para que sus combinaciones se
    crucen entre sí sin repetir siempre el mismo par.
    """
    carpeta = Path(carpeta)
    sembradas = atenciones_de_relleno(carpeta)
    cambios: dict[str, dict[str, dict]] = {}

    def anotar(tabla: str, llave: str, valores: dict) -> None:
        cambios.setdefault(tabla, {}).setdefault(llave, {}).update(valores)

    llegadas = {f[CLAVE_ATENCION]: f[LLEGADA] for f in pq.read_table(
        carpeta / "informacion_demografica.parquet", columns=[CLAVE_ATENCION, LLEGADA]).to_pylist()}

    for j, llave in enumerate(sembradas):
        # Mecanismos: los que no están en el patrón quedan vacíos; los presentes conservan sus valores generados
        presentes = PATRONES_MECANISMO[j % len(PATRONES_MECANISMO)]
        for mecanismo in MECANISMOS:
            if mecanismo in presentes:
                continue
            for tabla, columnas in COLUMNAS_DEL_MECANISMO[mecanismo][fuente]:
                anotar(tabla, llave, dict.fromkeys(columnas))

        ocular, verbal, motor, sistolica, frecuencia = SIGNOS[j % len(SIGNOS)]
        anotar("signos_vitales", llave, {
            "gcs_ocular": ocular, "gcs_verbal": verbal, "gcs_motora": motor,
            "presion_arterial_sistolica": sistolica, "frecuencia_cardiaca": frecuencia})
        anotar("liquidos", llave, {"sangre": SANGRE[j % len(SANGRE)]})
        anotar("puntuacion_de_severidad", llave, {"iss": ISS[j % len(ISS)]})
        anotar(TABLA_DE_DISPOSICION[fuente], llave, {"disposicion_o_destino_del_paciente": DISPOSICIONES[j % len(DISPOSICIONES)]})

        # Alta: la fecha de llegada más los días de la estancia, a la hora de uno de los bordes del día; sin estancia, sin alta
        estancia, llegada = ESTANCIAS[j % len(ESTANCIAS)], llegadas[llave]
        hora, minuto = HORAS_DE_ALTA[j % len(HORAS_DE_ALTA)]
        alta = None if estancia is None or llegada is None else (
            llegada.replace(hour=hora, minute=minuto, second=0, microsecond=0) + timedelta(days=estancia))
        anotar("hospitalizacion", llave, {"fecha_y_hora_de_alta": alta})

    # El orden del quinquenio de todas las atenciones (también los casos fijos) sigue a su etiqueta
    demografia = pq.read_table(carpeta / "informacion_demografica.parquet", columns=[CLAVE_ATENCION, "quinquenio_edad"])
    for fila in demografia.to_pylist():
        if fila["quinquenio_edad"] is not None:
            cambios.setdefault("informacion_demografica", {})[fila[CLAVE_ATENCION]] = {
                "quinquenio_orden": _orden_del_quinquenio(fila["quinquenio_edad"])}

    for tabla, por_atencion in cambios.items():
        _editar(carpeta, tabla, por_atencion)
    return sembradas
