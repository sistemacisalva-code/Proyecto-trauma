# REDCap transformer module
import logging

import pandas as pd

from config.settings import REDCAP_EXPORT_CONFIG, REDCAP_RAW_BASE_DIR, REDCAP_RENOMBRES_YAML_PATH
from etl.transform.base import BaseTransformer
from etl.transform.common.cleaning import aplicar_renombres, normalizar_columnas, vacios_a_nulo
from etl.transform.common.privacy import seudonimizar
from etl.transform.common.procedencia import huellas_configuracion
from etl.transform.common.quality import ReporteCalidad
from etl.transform.redcap.bloques import (
    CLAVE,
    EXCLUIR_DEL_DW,
    INSTRUMENTOS_ESPERADOS,
    dividir_en_bloques,
    resumir_bloques,
    resumir_descartes,
    validar_dependencias,
)
from etl.transform.redcap.consolidacion import consolidar_particiones, fecha_de_particion, leer_particiones
from etl.transform.redcap.cronologia import verificar_cronologia
from etl.transform.redcap.instrumentos import CATEGORICAS, TRANSFORMACIONES

logger = logging.getLogger(__name__)

COL_DOCUMENTO = "numero_de_identificacion"
COL_DOCUMENTO_SEUDONIMO = "documento_seudonimo"
COL_LLEGADA = "fecha_y_hora_de_llegada_del_paciente"
COLUMNAS_SISTEMA_A_ELIMINAR = ("redcap_repeat_instrument", "redcap_repeat_instance", "redcap_event_name")
_DEST_POR_DEFECTO = REDCAP_EXPORT_CONFIG["registro_trauma_longitudinal"]["dest"]


class REDCapTransformer(BaseTransformer):
    """
    Transforma la capa raw de REDCap en una tabla por instrumento.

    Orden de operaciones:
    consolidación de particiones -> nombres -> vacíos a nulo -> seudonimización -> duplicados (solo se
    marcan) -> división en bloques -> transformación por instrumento en el orden de
    INSTRUMENTOS_ESPERADOS -> eliminación de columnas de sistema. Las llaves y la verificación de la
    auditoría las completa `BaseTransformer.run()`.
    """

    source_type = "redcap"
    source_system = "redcap"
    tabla_base = "informacion_demografica"
    columnas_duplicado_negocio = (COL_DOCUMENTO_SEUDONIMO, COL_LLEGADA)

    def __init__(self, clave_seudonimizacion: str | bytes | None,
                 raw_dir: str = REDCAP_RAW_BASE_DIR,
                 dest: str = _DEST_POR_DEFECTO,
                 renombres_yaml: str = REDCAP_RENOMBRES_YAML_PATH,
                 particiones: dict[str, pd.DataFrame] | None = None):
        """
        Args:
            clave_seudonimizacion: clave del HMAC del documento (PSEUDONYMIZATION_KEY del .env).
            raw_dir, dest: carpeta raw y nombre del Parquet de las particiones `load_date=...`.
            renombres_yaml: renombres semánticos de columnas.
            particiones: DataFrames ya leídos {partición: DataFrame}; si se omite, se leen de raw_dir
                (permite probar el transformer con datos sintéticos, sin disco).
        """
        if not clave_seudonimizacion:
            raise ValueError("Falta la clave de seudonimización (PSEUDONYMIZATION_KEY en el .env)")
        self._clave = clave_seudonimizacion
        self._raw_dir = raw_dir
        self._dest = dest
        self._renombres_yaml = renombres_yaml
        self._particiones = particiones
        self._particiones_leidas: list[str] = []      # se completa al consolidar (procedencia)

    def procedencia(self) -> dict:
        """Particiones de raw consolidadas y huellas de la configuración usada (YAML de renombres, catálogos)."""
        return {"particiones_raw": self._particiones_leidas,
                "configuracion": huellas_configuracion([self._renombres_yaml])}

    def transform(self, reporte: ReporteCalidad) -> dict[str, pd.DataFrame]:
        validar_dependencias()
        df, fecha_extraccion = self._consolidar(reporte)
        df = self._preparar(df, reporte)

        bloques = dividir_en_bloques(df)
        # La división deja fuera los identificadores directos (decisión 2.8): cada uno queda en `exclusiones`
        for col in EXCLUIR_DEL_DW:
            if col in df.columns:
                reporte.registrar_exclusion("global", col, int(df[col].notna().sum()),
                                            "identificador directo o cuasi-identificador (sin uso analitico, Habeas Data)")
        # Antes de eliminar las columnas de sistema: `repetible` se calcula con redcap_repeat_instance
        reporte.registrar_resumen_bloques(resumir_bloques(bloques))
        # Filas que la división descartó por no tener datos del instrumento; se cuentan para que el descarte no sea invisible
        reporte.registrar_descartes(resumir_descartes(df))

        # El orden de INSTRUMENTOS_ESPERADOS es el de procesamiento; `transformados` solo contiene los
        # instrumentos anteriores, por lo que una dependencia mal ordenada falla con KeyError
        transformados: dict[str, pd.DataFrame] = {}
        for nombre in INSTRUMENTOS_ESPERADOS:
            bloque = bloques[nombre]
            reporte.perfilar(bloque, nombre, "antes", CATEGORICAS.get(nombre, ()))
            transformar = TRANSFORMACIONES.get(nombre)
            transformados[nombre] = transformar(bloque, reporte, transformados) if transformar else bloque
            logger.info(f"[redcap] '{nombre}': {len(transformados[nombre])} filas")

        # Necesita todos los instrumentos ya transformados; solo reporta (decisión 2.25)
        verificar_cronologia(transformados, reporte, fecha_extraccion)

        return self._finalizar(transformados, reporte)

    # --- Pasos ---------------------------------------------------------------------------
    def _consolidar(self, reporte: ReporteCalidad) -> tuple[pd.DataFrame, pd.Timestamp | None]:
        """Devuelve la foto consolidada y el momento de extracción (partición más reciente, no la hora actual)."""
        particiones = self._particiones
        if particiones is None:
            particiones = leer_particiones(self._raw_dir, self._dest)
        self._particiones_leidas = sorted(particiones)
        foto, resumen = consolidar_particiones(particiones)
        reporte.registrar_consolidacion(resumen)
        return foto, fecha_de_particion(max(particiones))

    def _preparar(self, df: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
        """Pasos globales previos a la división en bloques."""
        reporte.perfilar(df, "global", "antes")  # estado crudo: nombres, tipos y conteos originales

        df, equivalencia = normalizar_columnas(df)
        df, equivalencia = aplicar_renombres(df, equivalencia, self._renombres_yaml)
        reporte.registrar_equivalencia(equivalencia)

        # Obligatorio antes de cualquier verificación: en modo "label" los vacíos llegan como texto
        df = vacios_a_nulo(df)

        df = self._seudonimizar_documento(df, reporte)

        # Los duplicados solo se marcan; qué hacer con ellos es una decisión posterior (decisión 2.2).
        # Nivel 1 y 2 usan ignorar_nulos=False: en un export longitudinal los nulos son estructurales.
        reporte.marcar_duplicados(df, "global", "fila_exacta", list(df.columns), ignorar_nulos=False)
        reporte.marcar_duplicados(df, "global", "clave_estructural", CLAVE, ignorar_nulos=False)
        reporte.marcar_duplicados(df, "global", "regla_negocio", [COL_DOCUMENTO_SEUDONIMO, COL_LLEGADA])
        return df

    def _seudonimizar_documento(self, df: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
        """Reemplaza el documento por su seudónimo en la MISMA posición de la columna original, para que
        siga dentro del grupo de columnas del instrumento demográfico al dividir por `*_complete`."""
        if COL_DOCUMENTO not in df.columns:
            raise KeyError(f"No existe la columna '{COL_DOCUMENTO}' en el export")
        posicion = df.columns.get_loc(COL_DOCUMENTO)
        df.insert(posicion, COL_DOCUMENTO_SEUDONIMO, seudonimizar(df[COL_DOCUMENTO], self._clave))
        reporte.registrar_renombre("global", COL_DOCUMENTO, COL_DOCUMENTO_SEUDONIMO,
                                   "seudonimizacion HMAC-SHA256: el documento no llega en claro a la bodega")
        return df.drop(columns=COL_DOCUMENTO)

    def _finalizar(self, bloques: dict[str, pd.DataFrame], reporte: ReporteCalidad) -> dict[str, pd.DataFrame]:
        """Elimina las columnas de sistema al último momento y perfila el estado final de cada bloque."""
        finales = {}
        for nombre, df in bloques.items():
            columnas = [c for c in COLUMNAS_SISTEMA_A_ELIMINAR if c in df.columns]
            sin_sistema = df.drop(columns=columnas)
            # Filas que solo se vuelven idénticas al perder la instancia: evidencia de que la eliminación
            # colapsa filas distintas dentro de un mismo record_id
            antes = df.duplicated(keep=False)
            despues = sin_sistema.duplicated(keep=False)
            reporte.reportar_regla(nombre, "filas identicas solo tras eliminar columnas de sistema",
                                   pd.Series(True, index=df.index), despues & ~antes, reporte.llaves(df))
            reporte.perfilar(sin_sistema, nombre, "despues", CATEGORICAS.get(nombre, ()))
            finales[nombre] = sin_sistema
        return finales
