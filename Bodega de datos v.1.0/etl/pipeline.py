"""
Pipeline ETL del Data Warehouse de Trauma.

Puntos de entrada (selección obligatoria vía --mode, sin valor por defecto):
    --mode=excel-registro-antiguo   Carga histórica única desde el Excel antiguo.
    --mode=redcap                   Extracción periódica desde REDCap (solo lectura, a Parquet).
    --mode=transform-redcap         Transformación de toda la capa raw de REDCap hacia staging.
    --mode=transform-excel          Transformación de la carga histórica del Excel hacia staging.
    --mode=load                     Carga del staging de una fuente a un modelo de la bodega
                                    (exige --modelo y --fuente).
    --mode=all                      ETL completo de un modelo (--modelo, 'completo' por defecto): REDCap
                                    (extracción, transformación y carga), el Excel histórico si todavía no se
                                    cargó en ese modelo y, al final, el reporte de calidad de la bodega. Nunca
                                    usa --force. Un candado impide dos corridas a la vez. --sin-excel deja el
                                    Excel fuera y --sin-extraccion usa la capa raw que ya hay en disco.

Uso:
    python -m etl.pipeline --mode=all
    python -m etl.pipeline --mode=all --modelo=completo --sin-excel
    python -m etl.pipeline --mode=excel-registro-antiguo
    python -m etl.pipeline --mode=excel-registro-antiguo --force
    python -m etl.pipeline --mode=redcap
    python -m etl.pipeline --mode=transform-redcap
    python -m etl.pipeline --mode=transform-excel
    python -m etl.pipeline --mode=load --modelo=completo --fuente=redcap
    python -m etl.pipeline --mode=load --modelo=completo --fuente=excel --force
"""
import argparse
from contextlib import contextmanager
from datetime import datetime
import logging
import os
import sys

import pandas as pd
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine

from config.settings import (
    CONTRATOS_DIR,
    DATABASE_YAML_PATH,
    EXCEL_RAW_BASE_DIR,
    EXCEL_SHEETS_CONFIG,
    EXCEL_SOURCE_PATH,
    PSEUDONYMIZATION_KEY,
    QUALITY_REPORTS_BASE_DIR,
    QUARANTINE_BASE_DIR,
    VALORES_PERMITIDOS_YAML_PATH,
    REDCAP_EXPORT_CONFIG,
    REDCAP_RAW_BASE_DIR,
    REDCAP_API_TOKEN,
    REDCAP_API_URL,
    STAGING_BASE_DIR,
)
from etl.extract.excel_extractor import ExcelExtractor
from etl.extract.factory import ExtractorFactory
from etl.load.parquet_writer import save_extraction_result
from etl.load.staging_writer import save_transform_result
from etl.load.warehouse.contrato import FUENTES, leer_contrato
from etl.load.warehouse.factory import MODELOS, LoaderFactory
from etl.quality.dominios import leer_permitidos
from etl.quality.reporte import construir_reporte
from etl.transform.factory import TransformerFactory

logger = logging.getLogger(__name__)

EXCEL_CONTROL_SOURCE = "excel:historico"
# A diferencia de Excel, REDCap es periódico: no hay guardia de idempotencia,
# solo se registra cada corrida exitosa en etl_control.extraccion.
REDCAP_CONTROL_SOURCE = "redcap:incremental"

# Reglas que el log de la calidad lista como motivo del veredicto; el resto queda en reglas.csv del reporte
LIMITE_MOTIVOS_EN_LOG = 30
# Código de salida de --mode=all cuando el reporte de calidad rechaza la bodega (1 queda para los fallos técnicos)
CODIGO_RECHAZADA = 2

# Llave del candado de la corrida completa (pg_advisory_lock admite un entero de 64 bits; el valor es arbitrario)
CLAVE_CANDADO_ETL = 7204001


# ---------------------------------------------------------------------------
# Tabla de control (etl_control.extraccion)
# ---------------------------------------------------------------------------

def _crear_engine() -> Engine:
    """
    Crea un engine de SQLAlchemy con las credenciales de la aplicación del entorno
    activo (variable APP_ENV, "development" por defecto), leídas de config/database.yaml.

    Se construye con URL.create (no con un f-string) para que caracteres especiales
    en la contraseña, como "@" o ":", no rompan la URL de conexión.
    """
    with open(DATABASE_YAML_PATH, "r", encoding="utf-8") as f:
        config_completa = yaml.safe_load(os.path.expandvars(f.read()))

    entorno_config = config_completa[os.environ.get("APP_ENV", "development")]
    url = URL.create(
        drivername=entorno_config["adapter"],
        username=entorno_config["username"],
        password=entorno_config["password"],
        host=entorno_config["host"],
        port=int(entorno_config["port"]),
        database=entorno_config["database"],
    )
    return create_engine(url)


def existe_corrida_exitosa(fuente: str) -> bool:
    """
    Consulta etl_control.extraccion y verifica si ya existe al menos una corrida
    marcada como exitosa para la fuente indicada.

    Args:
        fuente (str): identificador de la fuente (ej. "excel:historico").

    Returns:
        bool: True si ya hubo una corrida exitosa previa, False en caso contrario.
    """
    engine = _crear_engine()
    try:
        with engine.connect() as conexion:
            return conexion.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM etl_control.extraccion "
                    "WHERE fuente = :fuente AND exitosa)"
                ),
                {"fuente": fuente},
            ).scalar()
    finally:
        engine.dispose()


def obtener_ultima_corrida_exitosa(fuente: str) -> datetime | None:
    """
    Consulta etl_control.extraccion y devuelve el momento (ejecutado_en) de la
    corrida exitosa más reciente para la fuente indicada. Es la base de la
    ventana incremental de REDCap: no agrega ninguna columna nueva, reutiliza
    la marca de tiempo que ya registra cada corrida.

    Args:
        fuente (str): identificador de la fuente (ej. "redcap:incremental").

    Returns:
        datetime | None: instante de la última corrida exitosa, o None si nunca
            hubo una (primera corrida: se interpreta como "extraer todo").
    """
    engine = _crear_engine()
    try:
        with engine.connect() as conexion:
            return conexion.execute(
                text(
                    "SELECT MAX(ejecutado_en) FROM etl_control.extraccion "
                    "WHERE fuente = :fuente AND exitosa"
                ),
                {"fuente": fuente},
            ).scalar()
    finally:
        engine.dispose()


def excel_cargado(modelo: str) -> bool:
    """
    Indica si el Excel ya se cargó con éxito en el modelo: la misma consulta de la guardia del Loader,
    sobre etl_control.carga. Es lo que decide si la corrida completa incluye o no el Excel.
    """
    engine = _crear_engine()
    try:
        with engine.connect() as conexion:
            return conexion.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM etl_control.carga "
                    "WHERE modelo = :modelo AND fuente = 'excel' AND exitosa)"
                ),
                {"modelo": modelo},
            ).scalar()
    finally:
        engine.dispose()


@contextmanager
def candado_del_etl():
    """
    Candado de sesión de PostgreSQL (pg_try_advisory_lock) que impide dos corridas completas a la vez, por ejemplo
    un botón pulsado dos veces. No espera: si está ocupado falla. Se libera al terminar o, si el proceso muere, al
    cerrarse la conexión, así que no puede quedar tomado para siempre.

    Raises:
        RuntimeError: si ya hay una corrida completa en curso.
    """
    engine = _crear_engine()
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conexion:
            if not conexion.execute(text("SELECT pg_try_advisory_lock(:clave)"), {"clave": CLAVE_CANDADO_ETL}).scalar():
                raise RuntimeError("Ya hay una corrida completa del ETL en curso; espere a que termine.")
            try:
                yield
            finally:
                conexion.execute(text("SELECT pg_advisory_unlock(:clave)"), {"clave": CLAVE_CANDADO_ETL})
    finally:
        engine.dispose()


def registrar_corrida_exitosa(fuente: str, filas_extraidas: int) -> None:
    """
    Inserta en etl_control.extraccion una fila que marca la corrida como exitosa.
    Solo debe invocarse cuando TODO el proceso terminó sin errores fatales.

    Args:
        fuente (str): identificador de la fuente (ej. "excel:historico").
        filas_extraidas (int): total de filas extraídas sumando todas las hojas.
    """
    engine = _crear_engine()
    try:
        with engine.begin() as conexion:
            conexion.execute(
                text(
                    "INSERT INTO etl_control.extraccion (fuente, filas_extraidas, exitosa) "
                    "VALUES (:fuente, :filas_extraidas, true)"
                ),
                {"fuente": fuente, "filas_extraidas": filas_extraidas},
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Carga histórica de Excel
# ---------------------------------------------------------------------------

def run_historical_excel_load(
    force: bool = False,
    source_path: str = EXCEL_SOURCE_PATH,
    sheets_config: dict = EXCEL_SHEETS_CONFIG,
    base_dir: str = EXCEL_RAW_BASE_DIR,
) -> None:
    """
    Ejecuta la carga histórica única del Excel antiguo hacia data/raw en Parquet.

    Args:
        force (bool): si es True, ignora la guardia de idempotencia y permite
            repetir la carga aunque ya exista una corrida exitosa registrada.
        source_path (str): ruta del Excel fuente (por defecto, el de settings.py).
        sheets_config (dict): hojas a extraer; cada valor lleva "sheet_name" (nombre
            real en el Excel) y "dest" (nombre del archivo de salida).
        base_dir (str): carpeta raíz de salida en la capa raw.

    Raises:
        RuntimeError: si ya existe una corrida exitosa y force es False.
        ValueError: si alguna hoja de sheets_config no existe en el archivo.
        FileNotFoundError: si source_path no existe.

    Política de errores por hoja: todo-o-nada. Si una hoja falla, se propaga la
    excepción y NO se registra corrida exitosa (así la próxima ejecución no queda
    bloqueada por la guardia).
    """
    if existe_corrida_exitosa(EXCEL_CONTROL_SOURCE) and not force:
        raise RuntimeError(
            "La carga histórica de Excel ya se ejecutó exitosamente antes. "
            "Si realmente necesita repetirla, use --force."
        )

    ExcelExtractor.validate_configured_sheets(source_path, sheets_config)

    filas_totales = 0
    hojas_procesadas = 0
    workbook = pd.ExcelFile(source_path, engine="calamine")
    try:
        for cfg in sheets_config.values():
            extractor = ExtractorFactory.get_extractor(
                "excel", {"source": workbook, "sheet_name": cfg["sheet_name"]}
            )
            result = extractor.run()
            ruta = save_extraction_result(result, dest_name=cfg["dest"], base_dir=base_dir)

            filas_totales += result.rows
            hojas_procesadas += 1
            logger.info(f"Hoja '{cfg['sheet_name']}': {result.rows} filas -> {ruta}")
    finally:
        workbook.close()

    registrar_corrida_exitosa(EXCEL_CONTROL_SOURCE, filas_totales)
    logger.info(
        f"Carga histórica de Excel completa: {hojas_procesadas} hojas, "
        f"{filas_totales} filas en total, guardadas bajo '{base_dir}'."
    )


# ---------------------------------------------------------------------------
# Extracción periódica de REDCap
# ---------------------------------------------------------------------------

def run_incremental_redcap(
    base_dir: str = REDCAP_RAW_BASE_DIR,
    export_config: dict = REDCAP_EXPORT_CONFIG,
    api_url: str = REDCAP_API_URL,
    api_token: str = REDCAP_API_TOKEN,
) -> None:
    """
    Extracción periódica desde REDCap hacia data/raw en Parquet. Solo lectura:
    la fuente nunca se modifica (el extractor solo exporta y el token debe ser
    de solo lectura en REDCap); lo único que se escribe es la copia local.

    Args:
        base_dir (str): carpeta raíz de salida en la capa raw.
        export_config (dict): equivalente a REDCAP_EXPORT_CONFIG de config/settings.py.
            Cada entrada lleva "export_fields" (None = todas), "dest" (nombre del
            Parquet) y "expected_n_columns" (None = sin control; ver más abajo).
        api_url (str): URL de la API de REDCap (del .env, vía settings.py).
        api_token (str): token de solo lectura (del .env, vía settings.py).

    Raises:
        ValueError: si el número de columnas observado no coincide con
            "expected_n_columns" (deriva del esquema en REDCap) o si falta la
            URL/token.

    Política de errores: todo-o-nada. Si algo falla no se registra corrida exitosa.

    Ventana incremental: date_begin es el "ejecutado_en" de la última corrida exitosa
    de REDCAP_CONTROL_SOURCE (None en la primera corrida, que trae todo el histórico).
    date_end no se fija: se deja abierto hasta el momento de la extracción. Ojo con
    zonas horarias: "ejecutado_en" es TIMESTAMPTZ y REDCap compara contra la hora de
    su propio servidor; si difieren, verificar el desfase antes de confiar en el corte.
    """
    # Partición única por corrida (fecha y hora, sin ":" por Windows): la capa raw
    # es de solo agregado y dos corridas el mismo día no se sobrescriben.
    particion = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    filas_totales = 0

    date_begin = obtener_ultima_corrida_exitosa(REDCAP_CONTROL_SOURCE)
    if date_begin is None:
        logger.info(f"Sin corridas previas de '{REDCAP_CONTROL_SOURCE}': se extrae el histórico completo.")
    else:
        logger.info(f"Extracción incremental desde {date_begin.isoformat()}.")

    for nombre, cfg in export_config.items():
        extractor = ExtractorFactory.get_extractor(
            "redcap",
            {
                "api_url": api_url,
                "api_token": api_token,
                "export_fields": cfg.get("export_fields"),
                "date_begin": date_begin,
            },
        )
        result = extractor.run()

        # Control de deriva del esquema: opcional. En la primera corrida se deja en
        # None, se lee el conteo observado del log y se fija en settings.py.
        columnas = result.data.shape[1]
        esperadas = cfg.get("expected_n_columns")
        if result.rows == 0:
            # 0 filas (sin cambios desde la última corrida) no es deriva de esquema:
            # pd.DataFrame([]) da 0 columnas y no debe compararse contra "esperadas".
            logger.info(f"'{nombre}': 0 filas nuevas desde la última corrida (nada que actualizar)")
        elif esperadas is None:
            logger.info(f"'{nombre}': columnas observadas = {columnas} (sin control configurado)")
        elif columnas != esperadas:
            raise ValueError(
                f"'{nombre}': se esperaban {esperadas} columnas y REDCap devolvió {columnas}. "
                "Posible cambio de esquema en el proyecto REDCap; revisar antes de continuar."
            )

        ruta = save_extraction_result(
            result, dest_name=cfg["dest"], base_dir=base_dir, load_date=particion
        )
        filas_totales += result.rows
        logger.info(f"'{nombre}': {result.rows} filas -> {ruta}")

    registrar_corrida_exitosa(REDCAP_CONTROL_SOURCE, filas_totales)
    logger.info(f"Extracción de REDCap completa: {filas_totales} filas bajo '{base_dir}'.")


# ---------------------------------------------------------------------------
# Transformación de REDCap
# ---------------------------------------------------------------------------

def run_transform_redcap(
    raw_dir: str = REDCAP_RAW_BASE_DIR,
    staging_dir: str = os.path.join(STAGING_BASE_DIR, "redcap"),
    reports_dir: str = QUALITY_REPORTS_BASE_DIR,
    clave_seudonimizacion: str | None = PSEUDONYMIZATION_KEY,
) -> None:
    """
    Transforma toda la capa raw de REDCap y escribe el resultado en staging.

    Args:
        raw_dir (str): carpeta raw con las particiones `load_date=...`.
        staging_dir (str): carpeta de salida; se reemplaza completa en cada corrida (foto derivada).
        reports_dir (str): raíz de los reportes de calidad; cada corrida agrega su carpeta.
        clave_seudonimizacion (str): clave del HMAC del documento (PSEUDONYMIZATION_KEY del .env).

    Raises:
        ValueError: si falta la clave, si el esquema de las particiones difiere o si alguna
            variable perdió datos sin explicación (la auditoría detiene la corrida).

    No registra nada en etl_control.extraccion: esa tabla describe extracciones, y la
    transformación es reproducible desde raw. Si falla, el staging anterior queda intacto.
    """
    transformer = TransformerFactory.get_transformer(
        "redcap", {"clave_seudonimizacion": clave_seudonimizacion, "raw_dir": raw_dir}
    )
    result = transformer.run()
    rutas = save_transform_result(result, staging_dir=staging_dir, reports_dir=reports_dir)

    logger.info(
        f"Transformación de REDCap completa: {len(result.tables)} tablas, {sum(result.rows.values())} filas "
        f"-> '{rutas['staging']}'. Reporte de calidad en '{rutas['reporte']}'."
    )


# ---------------------------------------------------------------------------
# Transformación del Excel histórico
# ---------------------------------------------------------------------------

def run_transform_excel(
    raw_dir: str = EXCEL_RAW_BASE_DIR,
    staging_dir: str = os.path.join(STAGING_BASE_DIR, "excel"),
    reports_dir: str = QUALITY_REPORTS_BASE_DIR,
    clave_seudonimizacion: str | None = PSEUDONYMIZATION_KEY,
) -> None:
    """
    Transforma la carga histórica del Excel (partición más reciente de raw) y escribe el resultado en staging.

    Args:
        raw_dir (str): carpeta raw con las particiones `load_date=...` del Excel.
        staging_dir (str): carpeta de salida; se reemplaza completa en cada corrida (foto derivada).
        reports_dir (str): raíz de los reportes de calidad; cada corrida agrega su carpeta.
        clave_seudonimizacion (str): clave del HMAC (PSEUDONYMIZATION_KEY del .env), la misma de REDCap.

    Raises:
        ValueError: si falta la clave, si faltan o sobran hojas, si el mapeo de registro_trauma no cubre sus
            columnas o si alguna variable perdió datos sin explicación (la auditoría detiene la corrida).

    Igual que REDCap: no registra nada en etl_control.extraccion y, si falla, el staging anterior queda intacto.
    """
    transformer = TransformerFactory.get_transformer(
        "excel", {"clave_seudonimizacion": clave_seudonimizacion, "raw_dir": raw_dir}
    )
    result = transformer.run()
    rutas = save_transform_result(result, staging_dir=staging_dir, reports_dir=reports_dir)

    logger.info(
        f"Transformación del Excel completa: {len(result.tables)} tablas, {sum(result.rows.values())} filas "
        f"-> '{rutas['staging']}'. Reporte de calidad en '{rutas['reporte']}'."
    )


# ---------------------------------------------------------------------------
# Carga a la bodega
# ---------------------------------------------------------------------------

def run_load(
    modelo: str,
    fuente: str,
    force: bool = False,
    staging_base_dir: str = STAGING_BASE_DIR,
    contratos_dir: str = CONTRATOS_DIR,
    quarantine_dir: str = QUARANTINE_BASE_DIR,
    refresco_completo: bool = False,
) -> None:
    """
    Carga el staging de una fuente en un modelo de la bodega: una corrida por modelo y fuente,
    dentro de una transacción, que escribe solo las atenciones nuevas o modificadas de esa fuente y borra las que ya
    no están en el staging.

    Args:
        modelo (str): modelo destino ('completo' o 'mini').
        fuente (str): 'excel' o 'redcap'; se lee data/staging/<fuente>/.
        force (bool): repite la carga del Excel aunque ya haya una exitosa en ese modelo.
        refresco_completo (bool): reescribe todas las atenciones de la fuente, no solo las que cambiaron.
        staging_base_dir (str): raíz del staging.
        contratos_dir (str): carpeta con `<modelo>.yaml`.
        quarantine_dir (str): raíz de la cuarentena.

    Raises:
        ValueError: si no hay Loader para el modelo, si el staging no coincide con su manifiesto o la carga no
            reconcilia.
        ContratoInvalido: si el contrato está mal formado o pide columnas que el staging no tiene.
        RuntimeError: si el Excel ya se cargó en el modelo y force es False.

    El registro en etl_control.carga lo hace el Loader dentro de su transacción.
    """
    engine = _crear_engine()
    try:
        loader = LoaderFactory.get_loader(modelo, {
            "fuente": fuente,
            "engine": engine,
            "staging_dir": os.path.join(staging_base_dir, fuente),
            "ruta_contrato": os.path.join(contratos_dir, f"{modelo}.yaml"),
            "quarantine_dir": quarantine_dir,
            "force": force,
            "refresco_completo": refresco_completo,
        })
        result = loader.run()
    finally:
        engine.dispose()

    totales = result.totales()
    logger.info(
        f"Carga de {fuente} en {modelo} completa (staging {result.run_id_staging}): "
        f"{totales['filas_cargadas']} filas cargadas, {totales['filas_no_usadas']} no usadas y "
        f"{totales['filas_cuarentena']} en cuarentena. Atenciones: {result.atenciones or 'sin conteo'}."
    )


# ---------------------------------------------------------------------------
# Calidad de la bodega cargada
# ---------------------------------------------------------------------------

def _rol_lector() -> str:
    """Nombre del rol lector (Power BI) del entorno activo, de config/database.yaml; solo se toma ese campo."""
    with open(DATABASE_YAML_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(os.path.expandvars(f.read()))
    return config[os.environ.get("APP_ENV", "development")]["reader"]


def run_quality(modelo: str, contratos_dir: str = CONTRATOS_DIR, reports_dir: str = QUALITY_REPORTS_BASE_DIR,
                staging_base_dir: str = STAGING_BASE_DIR,
                valores_permitidos_path: str = VALORES_PERMITIDOS_YAML_PATH) -> str:
    """
    Verifica la calidad de la bodega ya cargada de un modelo y escribe su reporte (md y CSV, solo conteos).

    Args:
        modelo (str): modelo a verificar ('completo' o 'mini').
        contratos_dir (str): carpeta con `<modelo>.yaml`.
        reports_dir (str): raíz de los reportes; cada corrida agrega su carpeta `carga_id=<n>`.
        staging_base_dir (str): raíz del staging, de donde sale la ida y vuelta contra la fuente.
        valores_permitidos_path (str): listas de valores permitidos por atributo (QR-DOM-04). Si el archivo no existe,
            la regla no se evalúa; si existe pero no es válido, lanza ValoresPermitidosInvalidos antes de tocar la base.

    Returns:
        El veredicto del reporte ('Aprobada', 'Aprobada con advertencias' o 'Rechazada').

    Es solo lectura sobre la bodega: lo único que escribe en la base es una fila de etl_control.calidad con el veredicto,
    los conteos de reglas y la carpeta del reporte (la tabla se crea con main.py; no borra nada). Un veredicto
    'Rechazada' no lanza error: la bodega ya está cargada y el reporte es quien lo informa; decidir qué hacer con él le
    toca a quien invoca.
    """
    contrato = leer_contrato(os.path.join(contratos_dir, f"{modelo}.yaml"), modelo)
    permitidos = (leer_permitidos(valores_permitidos_path, contrato) if os.path.exists(valores_permitidos_path)
                  else None)
    if permitidos is None:
        logger.info(f"Sin {valores_permitidos_path}: no se evalúa QR-DOM-04")
    engine = _crear_engine()
    try:
        with engine.connect() as conexion:
            reporte = construir_reporte(conexion, contrato, lector=_rol_lector(), reportes_dir=reports_dir,
                                        staging_dirs={f: os.path.join(staging_base_dir, f) for f in FUENTES},
                                        permitidos=permitidos)
        carpeta = reporte.escribir()
        veredicto = reporte.veredicto()
        resumen = reporte.resumen()
        logger.info(f"Reporte de calidad de {modelo} en {carpeta}: {veredicto}")
        for fila in resumen:
            logger.info(f"  {fila['dimension']}: {fila['cumplen']} cumplen, {fila['advierten']} advierten, "
                        f"{fila['fallan']} fallan")
        # Los motivos del veredicto: las reglas que fallan (bloquean) y las que advierten, con su conteo. El texto de cada
        # verificación solo nombra tablas y columnas; el reporte (reglas.csv) trae el resto
        motivos = sorted((r for r in reporte.reglas() if r["estado"] in ("Falla", "Advierte")),
                         key=lambda r: (r["estado"] != "Falla", r["regla"], r["verificacion"]))
        for r in motivos[:LIMITE_MOTIVOS_EN_LOG]:
            logger.info(f"  {r['estado']} {r['regla']}: {r['verificacion']} ({r['incumplen']} de {r['evaluadas']})")
        if len(motivos) > LIMITE_MOTIVOS_EN_LOG:
            logger.info(f"  ... y {len(motivos) - LIMITE_MOTIVOS_EN_LOG} más en reglas.csv")

        # El veredicto queda en la base (etl_control.calidad): solo conteos y la carpeta del reporte
        with engine.begin() as conexion:
            conexion.execute(
                text(
                    "INSERT INTO etl_control.calidad (modelo, veredicto, reglas_cumplen, reglas_advierten, "
                    "reglas_fallan, ruta_reporte) VALUES (:modelo, :veredicto, :cumplen, :advierten, :fallan, :ruta)"
                ),
                {"modelo": modelo, "veredicto": veredicto, "ruta": str(carpeta),
                 "cumplen": sum(f["cumplen"] for f in resumen), "advierten": sum(f["advierten"] for f in resumen),
                 "fallan": sum(f["fallan"] for f in resumen)},
            )
    finally:
        engine.dispose()
    return veredicto


# ---------------------------------------------------------------------------
# ETL completo
# ---------------------------------------------------------------------------

def run_all(modelo: str = "completo", incluir_excel: bool = True, extraer: bool = True) -> list[tuple[str, str]]:
    """
    ETL completo de un modelo, para ejecutarlo de una vez (línea de comandos o, a futuro, un botón): REDCap
    (extracción, transformación y carga), el Excel histórico si todavía no se cargó en el modelo y, al final, el
    reporte de calidad de la bodega. Los reportes de la transformación de cada fuente los escribe su propio paso.

    Args:
        modelo (str): modelo destino ('completo' o 'mini').
        incluir_excel (bool): si es False, la corrida no toca el Excel.
        extraer (bool): si es False, no extrae (ni de REDCap ni del Excel) y trabaja con la capa raw que ya hay en
            disco; sirve sin red o para repetir la transformación y la carga después de un fallo.

    Returns:
        [(paso, estado)] en el orden ejecutado; un paso del Excel ya cargado figura como "omitido" y el de calidad
        trae el veredicto. Un veredicto 'Rechazada' no es un fallo de la corrida: los datos ya se cargaron.

    Raises:
        RuntimeError: si ya hay otra corrida completa en curso (candado).
        Exception: la del primer paso que falle, sin cambios. La corrida se detiene ahí y no ejecuta los pasos
            siguientes: cada paso necesita el resultado del anterior.

    El Excel es histórico y no cambia: se incluye solo mientras no tenga una carga exitosa en el modelo, y esta función
    nunca usa force, así que repetirlo a la fuerza sigue siendo una decisión manual. Con el Excel ya cargado la
    corrida solo mueve REDCap.
    """
    pasos: list[tuple[str, str]] = []

    def paso(nombre: str, funcion, *args, **kwargs) -> None:
        logger.info(f"ETL completo: {nombre}...")
        try:
            funcion(*args, **kwargs)
        except Exception:
            logger.error(f"ETL completo detenido en el paso '{nombre}'.")
            raise
        pasos.append((nombre, "ok"))

    with candado_del_etl():
        if incluir_excel:
            if excel_cargado(modelo):
                logger.info(f"ETL completo: el Excel ya está cargado en '{modelo}'; se omite.")
                pasos.append(("excel", "omitido: ya cargado"))
            else:
                if extraer and not existe_corrida_exitosa(EXCEL_CONTROL_SOURCE):
                    paso("extraer excel", run_historical_excel_load)
                paso("transformar excel", run_transform_excel)
                paso("cargar excel", run_load, modelo, "excel")

        if extraer:
            paso("extraer redcap", run_incremental_redcap)
        else:
            pasos.append(("extraer", "omitido: se usa la capa raw existente"))
        paso("transformar redcap", run_transform_redcap)
        paso("cargar redcap", run_load, modelo, "redcap")

        logger.info("ETL completo: reporte de calidad de la bodega...")
        pasos.append(("calidad", f"veredicto: {run_quality(modelo)}"))

    logger.info("ETL completo terminado: " + "; ".join(f"{nombre}: {estado}" for nombre, estado in pasos))
    return pasos


def codigo_de_salida(pasos: list[tuple[str, str]]) -> int:
    """
    Código con el que termina `--mode=all`: 0 si la corrida terminó y la bodega no fue rechazada; 2 si el reporte de
    calidad dio "Rechazada" (CODIGO_RECHAZADA). Un fallo técnico no pasa por aquí: lanza la excepción del paso y el
    intérprete termina con 1. Así quien automatice la corrida (un servicio, un botón) distingue "no corrió" (1) de
    "corrió, pero la bodega no pasó la calidad" (2); los datos ya cargados no se revierten.
    """
    return CODIGO_RECHAZADA if ("calidad", "veredicto: Rechazada") in pasos else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    """
    Construye el parser de argumentos de línea de comandos.

    --mode es obligatorio y sin valor por defecto: nadie ejecuta una carga
    por accidente. --force es opcional y aplica a excel-registro-antiguo y a la
    carga del Excel a la bodega. --modelo y --fuente solo aplican a load.
    """
    parser = argparse.ArgumentParser(
        prog="etl.pipeline",
        description="Pipeline ETL del Data Warehouse de Trauma.",
        epilog="La carga histórica de Excel es de una sola vez; use --force solo si necesita repetirla.",
    )
    parser.add_argument("--mode", choices=["excel-registro-antiguo", "redcap", "transform-redcap", "transform-excel",
                                           "load", "all"],
                        required=True)
    parser.add_argument("--modelo", choices=list(MODELOS), default=None)
    parser.add_argument("--fuente", choices=list(FUENTES), default=None)
    parser.add_argument("--force", action="store_true", default=False)
    parser.add_argument("--full-refresh", action="store_true", default=False,
                        help="Solo con --mode=load: reescribe todas las atenciones de la fuente, no solo las que cambiaron")
    parser.add_argument("--sin-excel", action="store_true", default=False,
                        help="Solo con --mode=all: no incluye el Excel histórico aunque esté pendiente")
    parser.add_argument("--sin-extraccion", action="store_true", default=False,
                        help="Solo con --mode=all: no extrae y usa la capa raw que ya hay en disco (por ejemplo, sin red)")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Interpreta los argumentos y valida las combinaciones que argparse no expresa: load exige --modelo y
    --fuente (sin valor por defecto, como --mode); all acepta --modelo ('completo' por defecto) y --sin-excel, y
    nunca --force ni --fuente; los demás modos no aceptan ninguno de ellos.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.mode == "load" and (args.modelo is None or args.fuente is None):
        parser.error("--mode=load exige --modelo y --fuente")
    if args.mode == "all":
        if args.fuente is not None or args.force or args.full_refresh:
            parser.error("--mode=all solo acepta --modelo y --sin-excel (nunca --force: repetir el Excel es manual)")
        args.modelo = args.modelo or "completo"
    elif args.mode != "load" and (args.modelo is not None or args.fuente is not None):
        parser.error("--modelo y --fuente solo aplican a --mode=load")
    if args.mode != "load" and args.full_refresh:
        parser.error("--full-refresh solo aplica a --mode=load")
    if args.mode != "all" and (args.sin_excel or args.sin_extraccion):
        parser.error("--sin-excel y --sin-extraccion solo aplican a --mode=all")
    return args


def main() -> None:
    """
    Punto de entrada: parsea argumentos, configura logging y despacha al modo elegido.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    args = parse_args()

    if args.mode == "excel-registro-antiguo":
        run_historical_excel_load(force=args.force)
    elif args.mode == "redcap":
        run_incremental_redcap()
    elif args.mode == "transform-redcap":
        run_transform_redcap()
    elif args.mode == "transform-excel":
        run_transform_excel()
    elif args.mode == "load":
        run_load(modelo=args.modelo, fuente=args.fuente, force=args.force, refresco_completo=args.full_refresh)
    elif args.mode == "all":
        pasos = run_all(modelo=args.modelo, incluir_excel=not args.sin_excel, extraer=not args.sin_extraccion)
        sys.exit(codigo_de_salida(pasos))


if __name__ == "__main__":
    main()
