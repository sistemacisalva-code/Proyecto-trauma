"""
Verificaciones de calidad sobre la bodega ya cargada (catálogo en docs/tecnico/04_reglas_de_calidad.md).
Cada función consulta la base y devuelve conteos por regla (`Resultado`): nunca filas ni valores de
pacientes. Las pruebas (tests/quality_tests/) las ejecutan sobre la base de pruebas con defectos inyectados; el script
de reporte las ejecutará sobre la bodega real.

Reglas de este módulo: QR-INT-01 a 04 (integridad), QR-DUP-01 y 02 (unicidad), QR-EXA-01 y 03 (exactitud, a partir de
la bitácora de la carga en etl_control), QR-SEG-01 y 02 (seguridad) y QR-TRZ-01 a 03 (trazabilidad). QR-SEG-01 necesita
el nombre del rol lector y QR-TRZ-01, la carpeta de los reportes de la transformación; sin ellos no se ejecutan.
Las verificaciones de valores (completitud, validez, consistencia y tiempo) están en `valores.py`.
"""
from pathlib import Path

import pyarrow.parquet as pq
from sqlalchemy import String, inspect, text
from sqlalchemy.engine import Connection, Inspector

from etl.load.warehouse.contrato import CLAVE_ATENCION, Contrato
from etl.load.warehouse.por_contrato import COLUMNA_HUELLA, PREFIJOS
from etl.load.warehouse.resolucion import NO_APLICA, SIN_DATO
from etl.quality.comun import Resultado, columna_de, esquema_de, hecho_de, tabla_de, ultimas_cargas
from etl.quality.dominios import verificar_valores_permitidos
from etl.quality.origen import verificar_hecho_contra_staging
from etl.quality.puentes import verificar_puentes_contra_staging
from etl.quality.valores import (
    verificar_atenciones_sin_puente, verificar_campos_criticos, verificar_cie10_sin_codigo, verificar_completitud, verificar_consistencia,
    verificar_rangos, verificar_tiempo_completo,
)

TIPOS_CON_FILAS_REPETIBLES = ("dimension", "catalogo", "puente")

# Columnas que el rol lector no puede leer: texto clínico libre (Habeas Data) y la huella de la carga incremental
# (dato técnico, mínimo privilegio). Debe coincidir con la lista de exclusión de database/schema/04_permissions.sql;
# una prueba unitaria lo comprueba.
COLUMNAS_RESERVADAS = (
    ("fact_trauma", "detalles_hospitalizacion"),
    ("fact_trauma", "huella"),
    ("bridge_atencion_imagen", "descripcion_imagen"),
    ("bridge_atencion_cie_10", "texto_origen"),
    ("bridge_atencion_complicacion", "texto_origen"),
)
# Nombres de columna que sugerirían datos de identificación del paciente. "nombre" solo cuenta como columna propia o
# como nombre del paciente, de la persona o completo: nombre_mes y nombre_dia del calendario no identifican a nadie.
PATRON_IDENTIFICADORES = ("(documento|cedula|identificacion|apellido|telefono|direccion|correo|email"
                          "|^nombres?$|nombres?_(paciente|persona|completo))")


def _columnas_de_contenido(inspector: Inspector, esquema: str, tabla: str) -> list[str]:
    """Las columnas de la tabla sin su clave sustituta (una sola columna de identidad): lo que identifica una fila."""
    columnas = inspector.get_columns(tabla, schema=esquema)
    clave = inspector.get_pk_constraint(tabla, schema=esquema)["constrained_columns"]
    sustituta = None
    if len(clave) == 1:
        (definicion,) = [c for c in columnas if c["name"] == clave[0]]
        if definicion.get("identity") is not None or definicion.get("autoincrement") is True:
            sustituta = clave[0]
    return [c["name"] for c in columnas if c["name"] != sustituta]


def verificar_claves_foraneas(conexion: Connection, esquema: str) -> list[Resultado]:
    """
    QR-INT-01: por cada clave foránea del esquema, cuántas filas con valor apuntan a una fila que no existe. La base
    ya rechaza esas filas mientras la restricción exista; la verificación confirma que se cumple de hecho.
    """
    inspector = inspect(conexion)
    resultados = []
    for hija in sorted(inspector.get_table_names(schema=esquema)):
        for fk in inspector.get_foreign_keys(hija, schema=esquema):
            propias, referidas = fk["constrained_columns"], fk["referred_columns"]
            padre = tabla_de(conexion, fk.get("referred_schema") or esquema, fk["referred_table"])
            union = " AND ".join(f"h.{columna_de(conexion, a)} = p.{columna_de(conexion, b)}"
                                 for a, b in zip(propias, referidas))
            con_valor = " AND ".join(f"h.{columna_de(conexion, a)} IS NOT NULL" for a in propias)
            evaluadas, incumplen = conexion.execute(text(
                f"SELECT count(*) FILTER (WHERE {con_valor}), "
                f"count(*) FILTER (WHERE {con_valor} AND p.{columna_de(conexion, referidas[0])} IS NULL) "
                f"FROM {tabla_de(conexion, esquema, hija)} h LEFT JOIN {padre} p ON {union}"
            )).one()
            resultados.append(Resultado("QR-INT-01", f"{hija}.{','.join(propias)} -> {fk['referred_table']}",
                                        evaluadas, incumplen))
    return resultados


def verificar_dimensiones_del_hecho(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-INT-02 (TC-CAR-05): las claves del hecho hacia dimensiones nunca quedan en NULL; la carga escribe el miembro
    'Sin dato' o 'No aplica'. Las fechas y las horas sí admiten NULL y no se evalúan aquí.
    """
    hecho, definicion = hecho_de(contrato)
    tabla = tabla_de(conexion, esquema_de(contrato), hecho)
    resultados = []
    for columna, d in definicion["columnas"].items():
        if d.get("resolucion") != "dimension":
            continue
        evaluadas, incumplen = conexion.execute(text(
            f"SELECT count(*), count(*) FILTER (WHERE {columna_de(conexion, columna)} IS NULL) FROM {tabla}"
        )).one()
        resultados.append(Resultado("QR-INT-02", f"{hecho}.{columna}", evaluadas, incumplen))
    return resultados


def verificar_huellas(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-INT-04: toda atención del hecho tiene huella. Después de una carga exitosa el Loader deja la huella
    en cada atención que escribe; una atención sin ella (cargada antes de la carga incremental, o con la columna
    borrada) se tomaría por modificada en la carga siguiente. Cuenta las atenciones con la huella en NULL. El formato
    (64 hexadecimales) ya lo exige la restricción `ck_fact_huella`.
    """
    hecho, _ = hecho_de(contrato)
    total, sin_huella = conexion.execute(text(
        f"SELECT count(*), count(*) FILTER (WHERE {columna_de(conexion, COLUMNA_HUELLA)} IS NULL) "
        f"FROM {tabla_de(conexion, esquema_de(contrato), hecho)}"
    )).one()
    return [Resultado("QR-INT-04", f"{hecho}: atenciones con huella", total, sin_huella)]


def verificar_atenciones(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-DUP-01: la llave de la atención no se repite en el hecho y todas llevan el prefijo de su fuente (EX- o RC-),
    que es lo que permite reemplazar una fuente sin tocar la otra.
    """
    hecho, _ = hecho_de(contrato)
    clave = columna_de(conexion, CLAVE_ATENCION)
    sin_prefijo = " AND ".join(f"{clave} NOT LIKE '{prefijo}-%'" for prefijo in PREFIJOS.values())
    total, repetidas, sin_fuente = conexion.execute(text(
        f"SELECT count(*), count(*) - count(DISTINCT {clave}), count(*) FILTER (WHERE {sin_prefijo}) "
        f"FROM {tabla_de(conexion, esquema_de(contrato), hecho)}"
    )).one()
    return [Resultado("QR-DUP-01", f"{hecho}: sin repetir {CLAVE_ATENCION}", total, repetidas),
            Resultado("QR-DUP-01", f"{hecho}: prefijo de fuente", total, sin_fuente)]


def verificar_filas_repetidas(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-DUP-02: en dimensiones, catálogos y puentes, filas que repiten todas sus columnas salvo la clave sustituta
    (un NULL cuenta como igual a otro NULL, como en el UNIQUE NULLS NOT DISTINCT). Cuenta las filas sobrantes.
    """
    esquema = esquema_de(contrato)
    inspector = inspect(conexion)
    resultados = []
    for nombre, destino in contrato.tablas.items():
        if destino["tipo"] not in TIPOS_CON_FILAS_REPETIBLES:
            continue
        columnas = ", ".join(columna_de(conexion, c) for c in _columnas_de_contenido(inspector, esquema, nombre))
        tabla = tabla_de(conexion, esquema, nombre)
        evaluadas, sobrantes = conexion.execute(text(
            f"SELECT (SELECT count(*) FROM {tabla}), coalesce(sum(n - 1), 0) "
            f"FROM (SELECT count(*) AS n FROM {tabla} GROUP BY {columnas}) g WHERE n > 1"
        )).one()
        resultados.append(Resultado("QR-DUP-02", nombre, evaluadas, int(sobrantes)))
    return resultados


def verificar_miembros_por_defecto(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-INT-03: cada miembro por defecto existe como máximo una vez en su tabla. Es 'Sin dato' (todos los atributos de
    texto en 'Sin dato') en las dimensiones, 'No aplica' en las que el contrato declara `vacio: no_aplica`, y el texto
    de lo no mapeado (`SIN CODIGO CIE-10`) en los catálogos que lo tienen. Una verificación por tabla: evaluadas 1;
    incumple si el miembro está repetido. Que falte no incumple: solo existe si alguna atención lo usa.
    """
    esquema = esquema_de(contrato)
    inspector = inspect(conexion)
    resultados = []
    for nombre, destino in contrato.tablas.items():
        if destino["tipo"] == "dimension":
            marcador = NO_APLICA if destino.get("vacio") == "no_aplica" else SIN_DATO
            textos = [c["name"] for c in inspector.get_columns(nombre, schema=esquema)
                      if isinstance(c["type"], String) and not c.get("identity")]
            if not textos:
                continue
            donde = " AND ".join(f"{columna_de(conexion, c)} = :marcador" for c in textos)
        elif destino["tipo"] == "catalogo" and "sin_mapeo" in destino:
            marcador = destino["sin_mapeo"]
            donde = f"{columna_de(conexion, destino['columna'])} = :marcador"
        else:
            continue
        presentes = conexion.execute(text(
            f"SELECT count(*) FROM {tabla_de(conexion, esquema, nombre)} WHERE {donde}"), {"marcador": marcador}).scalar()
        resultados.append(Resultado("QR-INT-03", f"{nombre}: miembro '{marcador}'", 1, int(presentes > 1)))
    return resultados


def verificar_reconciliacion(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-EXA-01: en la última carga exitosa de cada fuente, cuántos usos no cumplen leídas = cargadas + otra_toma +
    sin_valor + duplicado + cuarentena, releído de etl_control.carga_detalle. Una fuente sin carga
    exitosa no aparece.
    """
    resultados = []
    for fuente, carga_id in sorted(ultimas_cargas(conexion, contrato.modelo).items()):
        evaluadas, incumplen = conexion.execute(text(
            "SELECT count(*), count(*) FILTER (WHERE leidas <> cargadas + otra_toma + sin_valor + duplicado + cuarentena) "
            "FROM etl_control.carga_detalle WHERE carga_id = :carga"
        ), {"carga": carga_id}).one()
        resultados.append(Resultado("QR-EXA-01", f"{fuente} (carga {carga_id})", evaluadas, incumplen))
    return resultados


def verificar_filas_de_puentes(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-EXA-03: por puente (y por rol en CIE-10) y fuente, las filas que hay en la bodega frente a las `cargadas` que
    registró la última carga exitosa de la fuente. Detecta filas agregadas o borradas después de la carga. `incumplen`
    es la diferencia absoluta.
    """
    esquema = esquema_de(contrato)
    hecho, _ = hecho_de(contrato)
    clave_hecho = inspect(conexion).get_pk_constraint(hecho, schema=esquema)["constrained_columns"][0]
    ultimas = ultimas_cargas(conexion, contrato.modelo)
    resultados = []
    for nombre, tipo, bloque in contrato.bloques():
        if tipo != "puente":
            continue
        puente, _, rol = nombre.partition("[")
        for fuente, carga_id in sorted(ultimas.items()):
            tabla_staging = bloque["filas"][fuente]
            if tabla_staging is None:
                continue
            esperadas = conexion.execute(text(
                "SELECT coalesce(sum(cargadas), 0) FROM etl_control.carga_detalle "
                "WHERE carga_id = :carga AND destino = :destino AND tabla_staging = :tabla"
            ), {"carga": carga_id, "destino": nombre, "tabla": tabla_staging}).scalar()
            reales = conexion.execute(text(
                f"SELECT count(*) FROM {tabla_de(conexion, esquema, puente)} b "
                f"JOIN {tabla_de(conexion, esquema, hecho)} h ON h.{columna_de(conexion, clave_hecho)} = "
                f"b.{columna_de(conexion, clave_hecho)} "
                f"WHERE h.{columna_de(conexion, CLAVE_ATENCION)} LIKE :prefijo" + (" AND b.rol = :rol" if rol else "")
            ), {"prefijo": f"{PREFIJOS[fuente]}-%", **({"rol": rol.rstrip("]")} if rol else {})}).scalar()
            resultados.append(Resultado("QR-EXA-03", f"{nombre} ({fuente})", int(esperadas),
                                        abs(int(esperadas) - reales)))
    return resultados


def verificar_permisos_del_lector(conexion: Connection, contrato: Contrato, lector: str) -> list[Resultado]:
    """
    QR-SEG-01: el rol lector (el de Power BI) solo lee y no ve el texto clínico libre. Dos verificaciones:
    cuántas de las columnas reservadas puede leer (meta 0) y cuántas tablas del esquema puede modificar, con permiso
    de tabla o de alguna columna (meta 0). Consulta los privilegios efectivos del catálogo, no el script de permisos.
    """
    esquema = esquema_de(contrato)
    legibles = sum(bool(conexion.execute(
        text("SELECT has_column_privilege(:rol, :tabla, :columna, 'SELECT')"),
        {"rol": lector, "tabla": f"{esquema}.{tabla}", "columna": columna}).scalar())
        for tabla, columna in COLUMNAS_RESERVADAS)
    tablas = sorted(inspect(conexion).get_table_names(schema=esquema))
    modificables = sum(bool(conexion.execute(
        text("SELECT has_any_column_privilege(:rol, :tabla, 'INSERT,UPDATE,REFERENCES') "
             "OR has_table_privilege(:rol, :tabla, 'DELETE,TRUNCATE,TRIGGER')"),
        {"rol": lector, "tabla": f"{esquema}.{tabla}"}).scalar()) for tabla in tablas)
    return [Resultado("QR-SEG-01", "columnas reservadas sin lectura para el lector", len(COLUMNAS_RESERVADAS), legibles),
            Resultado("QR-SEG-01", "lector solo con lectura", len(tablas), modificables)]


def verificar_columnas_identificadoras(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-SEG-02: ninguna columna del esquema lleva un nombre que sugiera datos de identificación (documento, nombre,
    teléfono, etc.); del paciente solo existe el seudónimo. Es una auditoría de los nombres de columna (metadatos):
    no inspecciona el contenido del texto libre.
    """
    esquema = esquema_de(contrato)
    evaluadas, incumplen = conexion.execute(text(
        "SELECT count(*), count(*) FILTER (WHERE column_name ~* :patron) "
        "FROM information_schema.columns WHERE table_schema = :esquema"
    ), {"patron": PATRON_IDENTIFICADORES, "esquema": esquema}).one()
    return [Resultado("QR-SEG-02", f"{esquema}: columnas sin nombres de identificación", evaluadas, incumplen)]


def verificar_reportes_de_transformacion(conexion: Connection, contrato: Contrato, reportes_dir: str) -> list[Resultado]:
    """
    QR-TRZ-01: la última carga exitosa de cada fuente tiene, en disco, el reporte de calidad de la transformación de
    donde salió su staging (`<reportes_dir>/<fuente>/run_id=<run_id_staging>/`). Sin él no se puede trazar la bodega
    hasta su origen.
    """
    filas = conexion.execute(
        text("SELECT DISTINCT ON (fuente) id, fuente, run_id_staging FROM etl_control.carga "
             "WHERE modelo = :modelo AND exitosa ORDER BY fuente, id DESC"),
        {"modelo": contrato.modelo},
    ).all()
    return [Resultado("QR-TRZ-01", f"{fuente} (carga {carga_id}, staging {run_id})", 1,
                      int(not (Path(reportes_dir) / fuente / f"run_id={run_id}").is_dir()))
            for carga_id, fuente, run_id in filas]


def verificar_tablas_en_detalle(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-TRZ-02: en la última carga exitosa de cada fuente, cada tabla de staging que usa el contrato aparece en al menos
    un uso de `carga_detalle`: ninguna tabla leída quedó sin explicar. Cuenta las tablas que faltan.
    """
    resultados = []
    for fuente, carga_id in sorted(ultimas_cargas(conexion, contrato.modelo).items()):
        esperadas = set(contrato.columnas_por_tabla(fuente))
        presentes = set(conexion.execute(
            text("SELECT DISTINCT tabla_staging FROM etl_control.carga_detalle WHERE carga_id = :carga"),
            {"carga": carga_id}).scalars().all())
        resultados.append(Resultado("QR-TRZ-02", f"{fuente} (carga {carga_id})", len(esperadas),
                                    len(esperadas - presentes)))
    return resultados


def verificar_cuarentena_en_disco(conexion: Connection, contrato: Contrato) -> list[Resultado]:
    """
    QR-TRZ-03: lo que la bitácora cuenta en cuarentena en la última carga exitosa de cada fuente está en disco. Por cada
    tabla de staging con filas apartadas según `carga_detalle`, su Parquet en `ruta_cuarentena` existe y tiene ese número
    de filas; la carpeta no trae Parquet de otras tablas. Cada tabla que no cuadra cuenta 1; si la carpeta no existe (o
    no hay ruta), cuentan todas las tablas esperadas.

    Del Parquet solo se lee `num_rows` del pie del archivo (nunca valores ni el objeto de metadatos, que guarda mínimos y
    máximos por columna). Verifica la conservación del número de filas, no la integridad de su contenido.
    """
    resultados = []
    for fuente, carga_id in sorted(ultimas_cargas(conexion, contrato.modelo).items()):
        (ruta,) = conexion.execute(text("SELECT ruta_cuarentena FROM etl_control.carga WHERE id = :carga"),
                                   {"carga": carga_id}).one()
        esperadas = dict(conexion.execute(
            text("SELECT tabla_staging, max(cuarentena) FROM etl_control.carga_detalle WHERE carga_id = :carga "
                 "GROUP BY tabla_staging HAVING max(cuarentena) > 0"), {"carga": carga_id}).all())
        carpeta = Path(ruta) if ruta else None
        if carpeta is None or not carpeta.is_dir():
            incumplen = len(esperadas)
        else:
            archivos = {a.stem: a for a in carpeta.glob("*.parquet")}
            incumplen = sum(tabla not in archivos or pq.read_metadata(archivos[tabla]).num_rows != filas
                            for tabla, filas in esperadas.items()) + len(set(archivos) - set(esperadas))
        resultados.append(Resultado("QR-TRZ-03", f"{fuente} (carga {carga_id}, {len(esperadas)} tablas en cuarentena)",
                                    len(esperadas), incumplen))
    return resultados


def verificar_bodega(conexion: Connection, contrato: Contrato, lector: str | None = None,
                     reportes_dir: str | None = None, staging_dirs: dict[str, str] | None = None,
                     permitidos: dict[str, dict[str, list[str]]] | None = None) -> list[Resultado]:
    """
    Todas las verificaciones de este módulo, en el orden del catálogo. QR-SEG-01 solo se ejecuta si se da el nombre del
    rol `lector` y QR-TRZ-01 solo si se da la carpeta `reportes_dir` de los reportes de la transformación;
    QR-EXA-04 y 05 (ida y vuelta contra el staging) solo si se dan las carpetas `staging_dirs` ({fuente: carpeta});
    QR-DOM-04 solo si se dan las listas `permitidos` ({dimensión: {atributo: [valores]}}, de `dominios.leer_permitidos`).
    """
    resultados = [
        *verificar_claves_foraneas(conexion, esquema_de(contrato)),
        *verificar_dimensiones_del_hecho(conexion, contrato),
        *verificar_miembros_por_defecto(conexion, contrato),
        *verificar_huellas(conexion, contrato),
        *verificar_atenciones(conexion, contrato),
        *verificar_filas_repetidas(conexion, contrato),
        *verificar_reconciliacion(conexion, contrato),
        *verificar_filas_de_puentes(conexion, contrato),
    ]
    if lector:
        resultados += verificar_permisos_del_lector(conexion, contrato, lector)
    resultados += verificar_columnas_identificadoras(conexion, contrato)
    if reportes_dir:
        resultados += verificar_reportes_de_transformacion(conexion, contrato, reportes_dir)
    if staging_dirs:
        resultados += verificar_hecho_contra_staging(conexion, contrato, staging_dirs)
        resultados += verificar_puentes_contra_staging(conexion, contrato, staging_dirs)
    if permitidos:
        resultados += verificar_valores_permitidos(conexion, contrato, permitidos)
    return [
        *resultados,
        *verificar_tablas_en_detalle(conexion, contrato),
        *verificar_cuarentena_en_disco(conexion, contrato),
        *verificar_campos_criticos(conexion, contrato),
        *verificar_atenciones_sin_puente(conexion, contrato),
        *verificar_completitud(conexion, contrato),
        *verificar_rangos(conexion, contrato),
        *verificar_cie10_sin_codigo(conexion, contrato),
        *verificar_consistencia(conexion, contrato),
        *verificar_tiempo_completo(conexion, contrato),
    ]
