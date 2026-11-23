"""
Verificaciones de calidad sobre los valores de la bodega cargada (catálogo en docs/tecnico/04_reglas_de_calidad.md): completitud (QR-NUL-01 a 04), validez (QR-DOM-01 a 03), consistencia (QR-CON-01 a 06) y tiempo
completo (QR-TIE-01). Igual que `bodega.py`, devuelven solo conteos (`Resultado`).

Los rangos válidos no se copian: salen de los mismos módulos de la transformación que invalidan los valores fuera de
rango (`etl/transform/common/`), para que la transformación y la verificación no puedan desalinearse. Todos son
propuestas por validar con el equipo clínico; si cambian allá, cambian aquí.
"""
from datetime import date

from sqlalchemy import String, Text, inspect, text
from sqlalchemy.engine import Connection

from etl.load.warehouse.calendario import rango_calendario
from etl.load.warehouse.contrato import CLAVE_ATENCION, Contrato
from etl.load.warehouse.por_contrato import PREFIJOS
from etl.quality.comun import Resultado, columna_de, esquema_de, hecho_de, tabla_de
from etl.transform.common import laboratorio, liquidos, mecanismo, severidad, signos_vitales

SIN_DATO = "Sin dato"
SIN_TOPE = float("inf")

# columna del hecho -> (rango mínimo, máximo) de la transformación
RANGOS_GCS = {
    "gcs_ocular": signos_vitales.ESPECIFICACION_NUMERICA["gcs_ocular"][2],
    "gcs_verbal": signos_vitales.ESPECIFICACION_NUMERICA["gcs_verbal"][2],
    "gcs_motor": signos_vitales.ESPECIFICACION_NUMERICA["gcs_motora"][2],
}
RANGOS_DEL_HECHO = {
    **{columna: signos_vitales.ESPECIFICACION_NUMERICA[origen][2] for columna, origen in {
        "frecuencia_cardiaca": "frecuencia_cardiaca", "presion_sistolica": "presion_arterial_sistolica",
        "presion_diastolica": "presion_arterial_diastolica", "frecuencia_respiratoria": "frecuencia_respiratoria",
        "saturacion_o2": "saturacion_de_oxigeno", "temperatura_c": "temperatura", "peso": "peso",
        "altura": "altura"}.items()},
    "duracion_perdida_conciencia": (0, signos_vitales.LIMITE_PERDIDA_CONCIENCIA_MIN),
    **{region: severidad.ESPECIFICACION_SEVERIDAD[region][2] for region in severidad.REGIONES_ISS},
    "iss": severidad.ESPECIFICACION_SEVERIDAD["iss"][2],
    "scq": mecanismo.ESPECIFICACION_NUMERICA["scq"][1],
    "altura_metros": mecanismo.ESPECIFICACION_NUMERICA["altura_en_metros"][1],
    "pao2": laboratorio.ESPECIFICACION_NUMERICA["pao2"][2],
    "paco2": laboratorio.ESPECIFICACION_NUMERICA["paco2"][2],
    "sangre_l": (0, liquidos.LIMITE_DURO_LITROS["sangre"]),
    "dias_hospitalizacion": (0, SIN_TOPE),
    "uci_dias": (0, SIN_TOPE),
}
# Regla de cada campo crítico: la llave falla; la fecha de llegada solo advierte (decisión 2026-10-27, caso A)
CAMPOS_CRITICOS = {CLAVE_ATENCION: "QR-NUL-01", "fecha_admision_id": "QR-NUL-04"}
FECHAS_DEL_HECHO = ("fecha_admision_id", "fecha_hospitalizacion_id", "fecha_alta_id")


def _texto_del_rango(minimo: float, maximo: float) -> str:
    return f"{minimo:g} o más" if maximo == SIN_TOPE else f"entre {minimo:g} y {maximo:g}"


def _calendario(contrato: Contrato) -> tuple[str, str]:
    """Tabla del calendario y su columna de fecha, según el contrato."""
    (nombre,) = [t for t, d in contrato.tablas.items() if d["tipo"] == "calendario"]
    (columna,) = [c for c, d in contrato.tablas[nombre]["columnas"].items() if d["generado"] == "fecha"]
    return nombre, columna


def _clave_primaria(inspector, esquema: str, tabla: str) -> str:
    (clave,) = inspector.get_pk_constraint(tabla, schema=esquema)["constrained_columns"]
    return clave


def verificar_campos_criticos(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-NUL-01 (falla): la llave del hecho nunca está vacía; sin ella la atención no se puede identificar.
    QR-NUL-04 (advierte): la fecha de admisión (llegada del paciente) no está vacía; sin ella la atención no se ubica
    en el tiempo, pero se conserva el resto de su registro clínico.
    """
    hecho, _ = hecho_de(contrato)
    tabla = tabla_de(conexion, esquema_de(contrato), hecho)
    resultados = []
    for columna, regla in CAMPOS_CRITICOS.items():
        evaluadas, vacias = conexion.execute(text(
            f"SELECT count(*), count(*) FILTER (WHERE {columna_de(conexion, columna)} IS NULL) FROM {tabla}")).one()
        resultados.append(Resultado(regla, f"{hecho}.{columna}", evaluadas, vacias))
    return resultados


def verificar_atenciones_sin_puente(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-NUL-03 (informativa): por puente (y rol) y fuente, las atenciones del hecho que no tienen ninguna fila en él
    (evaluadas = atenciones de la fuente). Muchas son legítimas: una atención sin imágenes o sin complicaciones. Se
    reporta además el total de las fuentes, para ver el conjunto de la bodega.
    """
    esquema = esquema_de(contrato)
    hecho, _ = hecho_de(contrato)
    clave_hecho = _clave_primaria(inspect(conexion), esquema, hecho)
    resultados = []
    for nombre, tipo, bloque in contrato.bloques():
        if tipo != "puente":
            continue
        puente, _, rol = nombre.partition("[")
        parciales = []
        for fuente, tabla_filas in bloque["filas"].items():
            if tabla_filas is None:
                continue
            evaluadas, sin_filas = conexion.execute(text(
                f"SELECT count(*), count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM {tabla_de(conexion, esquema, puente)} b "
                f"WHERE b.{columna_de(conexion, clave_hecho)} = h.{columna_de(conexion, clave_hecho)}"
                + (" AND b.rol = :rol" if rol else "") + ")) "
                f"FROM {tabla_de(conexion, esquema, hecho)} h WHERE h.{columna_de(conexion, CLAVE_ATENCION)} LIKE :prefijo"
            ), {"prefijo": f"{PREFIJOS[fuente]}-%", **({"rol": rol.rstrip("]")} if rol else {})}).one()
            parciales.append((fuente, evaluadas, sin_filas))
        resultados += [Resultado("QR-NUL-03", f"{nombre} ({fuente}): atenciones sin filas", e, s)
                       for fuente, e, s in parciales]
        if len(parciales) > 1:
            resultados.append(Resultado("QR-NUL-03", f"{nombre} (total): atenciones sin filas",
                                        sum(e for _, e, _ in parciales), sum(s for _, _, s in parciales)))
    return resultados


def verificar_completitud(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-NUL-02 (informativa, sin umbral): por cada columna del hecho, cuántas filas están vacías. En medidas, fechas y
    texto libre, vacío es NULL; en los atributos de las dimensiones, `'Sin dato'` (o NULL si no es de texto). `'No
    aplica'` no cuenta: es un mecanismo que no ocurrió, no un dato faltante. Da la línea base de vacíos por columna
    para acordar los umbrales.
    """
    esquema = esquema_de(contrato)
    hecho, definicion = hecho_de(contrato)
    tabla = tabla_de(conexion, esquema, hecho)
    inspector = inspect(conexion)
    total = conexion.execute(text(f"SELECT count(*) FROM {tabla}")).scalar()
    resultados = []
    for columna, d in definicion["columnas"].items():
        if d.get("resolucion", "copia") == "dimension":
            continue
        if columna == CLAVE_ATENCION:
            continue
        vacias = conexion.execute(text(
            f"SELECT count(*) FILTER (WHERE {columna_de(conexion, columna)} IS NULL) FROM {tabla}")).scalar()
        resultados.append(Resultado("QR-NUL-02", f"{hecho}.{columna}", total, vacias))
    for columna, d in definicion["columnas"].items():
        if d.get("resolucion") != "dimension" or contrato.tablas[d["dimension"]]["tipo"] != "dimension":
            continue
        dimension = d["dimension"]
        clave = _clave_primaria(inspector, esquema, dimension)
        tipos = {c["name"]: c["type"] for c in inspector.get_columns(dimension, schema=esquema)}
        for atributo in contrato.tablas[dimension]["columnas"]:
            propio = f"d.{columna_de(conexion, atributo)}"
            vacio = f"{propio} = '{SIN_DATO}'" if isinstance(tipos[atributo], (Text, String)) else f"{propio} IS NULL"
            vacias = conexion.execute(text(
                f"SELECT count(*) FILTER (WHERE {vacio}) FROM {tabla} f "
                f"JOIN {tabla_de(conexion, esquema, dimension)} d ON d.{columna_de(conexion, clave)} = "
                f"f.{columna_de(conexion, columna)}")).scalar()
            resultados.append(Resultado("QR-NUL-02", f"{dimension}.{atributo} (en {hecho})", total, vacias))
    return resultados


def verificar_rangos(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-DOM-01 (Glasgow) y QR-DOM-02 (demás medidas): por cada medida del hecho, cuántos valores caen fuera de su rango
    válido. La transformación ya invalida esos valores, así que en la bodega la meta es 0; confirma que ningún cambio
    posterior los dejó pasar. Evaluadas: las filas con valor.
    """
    hecho, _ = hecho_de(contrato)
    tabla = tabla_de(conexion, esquema_de(contrato), hecho)
    resultados = []
    for regla, rangos in (("QR-DOM-01", RANGOS_GCS), ("QR-DOM-02", RANGOS_DEL_HECHO)):
        for columna, (minimo, maximo) in rangos.items():
            propia = columna_de(conexion, columna)
            fuera = f"{propia} < :minimo" + (f" OR {propia} > :maximo" if maximo != SIN_TOPE else "")
            limites = {"minimo": minimo, **({"maximo": maximo} if maximo != SIN_TOPE else {})}
            evaluadas, incumplen = conexion.execute(text(
                f"SELECT count(*) FILTER (WHERE {propia} IS NOT NULL), "
                f"count(*) FILTER (WHERE {propia} IS NOT NULL AND ({fuera})) FROM {tabla}"
            ), limites).one()
            resultados.append(Resultado(regla, f"{hecho}.{columna} {_texto_del_rango(minimo, maximo)}",
                                        evaluadas, incumplen))
    return resultados


def verificar_cie10_sin_codigo(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-DOM-03 (informativa): por puente (y rol) con un catálogo que tiene miembro de lo no mapeado (CIE-10), cuántas filas
    apuntan a ese miembro (`SIN CODIGO CIE-10`) del total de filas del puente. Su texto original está en `texto_origen`.
    """
    esquema = esquema_de(contrato)
    inspector = inspect(conexion)
    resultados = []
    for nombre, tipo, bloque in contrato.bloques():
        if tipo != "puente":
            continue
        puente, _, rol = nombre.partition("[")
        for columna, d in bloque["columnas"].items():
            catalogo = contrato.tablas.get(d.get("dimension"), {})
            if d.get("resolucion") != "dimension" or catalogo.get("tipo") != "catalogo" or "sin_mapeo" not in catalogo:
                continue
            clave = _clave_primaria(inspector, esquema, d["dimension"])
            evaluadas, sin_codigo = conexion.execute(text(
                f"SELECT count(*), count(*) FILTER (WHERE c.{columna_de(conexion, catalogo['columna'])} = :sin_mapeo) "
                f"FROM {tabla_de(conexion, esquema, puente)} b "
                f"JOIN {tabla_de(conexion, esquema, d['dimension'])} c ON c.{columna_de(conexion, clave)} = "
                f"b.{columna_de(conexion, columna)}" + (" WHERE b.rol = :rol" if rol else "")
            ), {"sin_mapeo": catalogo["sin_mapeo"], **({"rol": rol.rstrip("]")} if rol else {})}).one()
            resultados.append(Resultado("QR-DOM-03", f"{nombre}: filas con '{catalogo['sin_mapeo']}'",
                                        evaluadas, sin_codigo))
    return resultados


def _fechas_en_orden(conexion: Connection, contrato: Contrato, regla: str, detalle: str, antes: str,
                     despues: str) -> Resultado:
    """Filas con las dos fechas donde la segunda es anterior a la primera (se compara el día en `dim_tiempo`)."""
    esquema = esquema_de(contrato)
    hecho, _ = hecho_de(contrato)
    calendario, fecha = _calendario(contrato)
    clave = _clave_primaria(inspect(conexion), esquema, calendario)
    tiempo = tabla_de(conexion, esquema, calendario)
    ambas = "a.{f} IS NOT NULL AND d.{f} IS NOT NULL".format(f=columna_de(conexion, fecha))
    evaluadas, incumplen = conexion.execute(text(
        f"SELECT count(*) FILTER (WHERE {ambas}), count(*) FILTER (WHERE {ambas} AND d.{columna_de(conexion, fecha)} "
        f"< a.{columna_de(conexion, fecha)}) FROM {tabla_de(conexion, esquema, hecho)} f "
        f"LEFT JOIN {tiempo} a ON a.{columna_de(conexion, clave)} = f.{columna_de(conexion, antes)} "
        f"LEFT JOIN {tiempo} d ON d.{columna_de(conexion, clave)} = f.{columna_de(conexion, despues)}"
    )).one()
    return Resultado(regla, detalle, evaluadas, incumplen)


def _horas_sin_fecha(contrato: Contrato) -> list[tuple[str, str, str]]:
    """(tabla, columna de fecha, columna de hora) de cada hora del contrato que sale del mismo origen que una fecha."""
    pares = []
    for nombre, _, bloque in contrato.bloques():
        columnas = bloque["columnas"]
        for hora, d in columnas.items():
            if d.get("resolucion") != "horario":
                continue
            (fecha,) = [c for c, f in columnas.items() if f.get("resolucion") == "calendario"
                        and f.get("origen") == d.get("origen")]
            pares.append((nombre.partition("[")[0], fecha, hora))
    return pares


def verificar_consistencia(conexion: Connection, contrato: Contrato, hoy: date | None = None) -> list[Resultado]:
    """
    Consistencia entre fechas y entre medidas, con conteos de las filas que la rompen:
      QR-CON-01 (advierte): alta anterior a la admisión (la traen las dos fuentes; la bodega no corrige el dato clínico).
      QR-CON-02 (advierte): hospitalización anterior a la admisión, o alta anterior a la hospitalización.
      QR-CON-03 (falla): una hora sin su fecha (alta del hecho e inicio de cada procedimiento).
      QR-CON-04 (advierte): fecha posterior a `hoy` (por defecto, el día de la verificación).
      QR-CON-05 (advierte): presión diastólica mayor que la sistólica.
      QR-CON-06 (advierte): días de UCI mayores que los de hospitalización.
    Las fechas se comparan por día: el hecho no guarda la hora de la admisión ni de la hospitalización.
    """
    esquema = esquema_de(contrato)
    hecho, _ = hecho_de(contrato)
    resultados = [
        _fechas_en_orden(conexion, contrato, "QR-CON-01", "alta no anterior a la admisión", "fecha_admision_id",
                         "fecha_alta_id"),
        _fechas_en_orden(conexion, contrato, "QR-CON-02", "hospitalización no anterior a la admisión",
                         "fecha_admision_id", "fecha_hospitalizacion_id"),
        _fechas_en_orden(conexion, contrato, "QR-CON-02", "alta no anterior a la hospitalización",
                         "fecha_hospitalizacion_id", "fecha_alta_id"),
    ]
    for tabla, fecha, hora in _horas_sin_fecha(contrato):
        evaluadas, incumplen = conexion.execute(text(
            f"SELECT count(*) FILTER (WHERE {columna_de(conexion, hora)} IS NOT NULL), "
            f"count(*) FILTER (WHERE {columna_de(conexion, hora)} IS NOT NULL AND {columna_de(conexion, fecha)} IS NULL) "
            f"FROM {tabla_de(conexion, esquema, tabla)}")).one()
        resultados.append(Resultado("QR-CON-03", f"{tabla}.{hora} con su fecha", evaluadas, incumplen))

    calendario, fecha = _calendario(contrato)
    clave = _clave_primaria(inspect(conexion), esquema, calendario)
    for columna in FECHAS_DEL_HECHO:
        evaluadas, futuras = conexion.execute(text(
            f"SELECT count(t.{columna_de(conexion, fecha)}), "
            f"count(*) FILTER (WHERE t.{columna_de(conexion, fecha)} > :hoy) "
            f"FROM {tabla_de(conexion, esquema, hecho)} f LEFT JOIN {tabla_de(conexion, esquema, calendario)} t "
            f"ON t.{columna_de(conexion, clave)} = f.{columna_de(conexion, columna)}"), {"hoy": hoy or date.today()}).one()
        resultados.append(Resultado("QR-CON-04", f"{hecho}.{columna} no posterior a hoy", evaluadas, futuras))

    for regla, detalle, mayor, menor in (
            ("QR-CON-05", "presión diastólica no mayor que la sistólica", "presion_diastolica", "presion_sistolica"),
            ("QR-CON-06", "días de UCI no mayores que los de hospitalización", "uci_dias", "dias_hospitalizacion")):
        ambas = f"{columna_de(conexion, mayor)} IS NOT NULL AND {columna_de(conexion, menor)} IS NOT NULL"
        evaluadas, incumplen = conexion.execute(text(
            f"SELECT count(*) FILTER (WHERE {ambas}), count(*) FILTER (WHERE {ambas} AND "
            f"{columna_de(conexion, mayor)} > {columna_de(conexion, menor)}) FROM {tabla_de(conexion, esquema, hecho)}"
        )).one()
        resultados.append(Resultado(regla, detalle, evaluadas, incumplen))
    return resultados


def verificar_tiempo_completo(conexion: Connection, contrato: Contrato, hoy: date | None = None) -> list[Resultado]:
    """
    QR-TIE-01: el horario tiene sus 1 440 minutos y el calendario empieza el día esperado y no tiene días faltantes.
    `incumplen` es la diferencia con 1 440 minutos y los días que faltan entre el primero y el último (más 1 si el
    primer día no es el del contrato).
    """
    esquema = esquema_de(contrato)
    resultados = []
    (horario,) = [t for t, d in contrato.tablas.items() if d["tipo"] == "horario"]
    minutos = conexion.execute(text(f"SELECT count(*) FROM {tabla_de(conexion, esquema, horario)}")).scalar()
    resultados.append(Resultado("QR-TIE-01", f"{horario}: 1440 minutos", 1440, abs(1440 - minutos)))

    calendario, fecha = _calendario(contrato)
    dias, primero, ultimo = conexion.execute(text(
        f"SELECT count(*), min({columna_de(conexion, fecha)}), max({columna_de(conexion, fecha)}) "
        f"FROM {tabla_de(conexion, esquema, calendario)}")).one()
    inicio = rango_calendario(hoy or date.today())[0]
    faltantes = ((ultimo - primero).days + 1 - dias) if dias else 0
    resultados.append(Resultado("QR-TIE-01", f"{calendario}: días consecutivos desde {inicio}", dias,
                                faltantes + (0 if primero == inicio else 1)))
    return resultados
