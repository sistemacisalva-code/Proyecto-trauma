# Excel transformer module
import logging

import pandas as pd

from config.settings import EXCEL_MAPEO_YAML_PATH, EXCEL_RAW_BASE_DIR, EXCEL_RENOMBRES_YAML_PATH
from etl.transform.base import BaseTransformer
from etl.transform.common.cie10 import cargar_universo
from etl.transform.common.cronologia import reportar_eventos_fuera_de_estancia
from etl.transform.common.procedencia import huellas_configuracion
from etl.transform.common.procedimientos import COL_ALTA, COL_LLEGADA
from etl.transform.common.quality import ReporteCalidad
from etl.transform.excel import hojas as hojas_hijas
from etl.transform.excel.preparacion import (
    CLAVE, EXCLUIR_DEL_DW, HOJA_BASE, edad_a_quinquenio, excluir_columnas, fechas_y_cronologia_registro,
    leer_particion_reciente, marcar_duplicados_registro, preparar_nombres_y_vacios, seudonimizar_identidad)
from etl.transform.excel.registro import leer_mapeo, transformar_registro

logger = logging.getLogger(__name__)

HOJAS_ESPERADAS = {HOJA_BASE, *hojas_hijas.TRANSFORMACIONES}
HOJAS_QUE_CAMBIAN_DE_GRANO = {"laboratorio"}   # una fila por examen -> una fila por toma (decisión 3.14)


class ExcelTransformer(BaseTransformer):
    """
    Transforma la carga histórica del Excel (capa raw, una partición) en staging completo: los bloques de
    registro_trauma con columnas propias y las hojas hijas, con nombres y reglas alineados a REDCap.

    Orden de operaciones: nombres y vacíos -> seudonimización -> exclusión -> fechas, cronología y edad ->
    duplicados, solo se marcan -> bloques de registro_trauma -> hojas hijas, incluido el mapeo CIE-10. Las llaves
    y la verificación de la auditoría las completa `BaseTransformer.run()`. Pendiente: la regla edad vs nacimiento.
    """

    source_type = "excel"
    source_system = "excel_historico"
    tabla_base = "informacion_demografica"
    columnas_duplicado_negocio = ("documento_seudonimo", COL_LLEGADA)

    def __init__(self, clave_seudonimizacion: str | bytes | None,
                 raw_dir: str = EXCEL_RAW_BASE_DIR,
                 renombres_yaml: str = EXCEL_RENOMBRES_YAML_PATH,
                 mapeo_yaml: str = EXCEL_MAPEO_YAML_PATH,
                 hojas: dict[str, pd.DataFrame] | None = None,
                 universo_cie10: pd.DataFrame | None = None):
        """
        Args:
            clave_seudonimizacion: clave del HMAC del documento (PSEUDONYMIZATION_KEY del .env), la misma de REDCap.
            raw_dir: carpeta raw con las particiones `load_date=...`; se usa la más reciente.
            renombres_yaml, mapeo_yaml: renombres por hoja y división de registro_trauma en bloques.
            hojas: {hoja: DataFrame} ya leídas; si se omite, se leen de raw_dir (permite probar sin disco).
            universo_cie10: catálogo + lista completa de CIE-10; si se omite se carga de config/catalogos.
        """
        if not clave_seudonimizacion:
            raise ValueError("Falta la clave de seudonimización (PSEUDONYMIZATION_KEY en el .env)")
        self._clave = clave_seudonimizacion
        self._raw_dir = raw_dir
        self._renombres_yaml = renombres_yaml
        self._mapeo_yaml = mapeo_yaml
        self._hojas = hojas
        self._universo = universo_cie10
        self._particion: str | None = None          # se completan al leer (procedencia)
        self._filas_entrada: dict[str, int] = {}

    def transform(self, reporte: ReporteCalidad) -> dict[str, pd.DataFrame]:
        hojas = self._leer()
        for hoja, df in hojas.items():
            reporte.perfilar(df, hoja, "antes")     # solo conteos: ninguna columna se declara categórica
        hojas = preparar_nombres_y_vacios(hojas, self._renombres_yaml, reporte)

        reg = self._preparar_registro(hojas[HOJA_BASE], reporte)
        tablas = transformar_registro(reg, leer_mapeo(self._mapeo_yaml), reporte)
        for nombre, df in tablas.items():           # cada bloque conserva todas las filas de registro_trauma
            reporte.registrar_balance(HOJA_BASE, len(hojas[HOJA_BASE]), nombre, len(df))

        universo = self._universo if self._universo is not None else cargar_universo()
        contexto = hojas_hijas.Contexto(registro=reg, universo_cie10=universo)
        for hoja, transformar in hojas_hijas.TRANSFORMACIONES.items():
            salida = transformar(hojas[hoja], reporte, contexto)
            self._balance_de_hoja(hoja, len(hojas[hoja]), salida, reporte)
            for nombre, df in salida.items():
                if nombre in tablas:
                    raise ValueError(f"Tabla de salida repetida: '{nombre}' (hoja {hoja})")
                tablas[nombre] = df
            logger.info(f"[excel] hoja '{hoja}' transformada")

        # Eventos fuera de la estancia (llegada -> alta, con margen): misma regla que REDCap (common/cronologia.py)
        episodio = reg.set_index(CLAVE)
        reportar_eventos_fuera_de_estancia(tablas, hojas_hijas.FECHAS_DE_EVENTO, episodio[COL_LLEGADA],
                                           episodio[COL_ALTA], reporte, llave=CLAVE)
        return self._finalizar(tablas, reporte)

    def procedencia(self) -> dict:
        """Partición de raw leída (None si las hojas se inyectaron), filas de entrada por hoja y huellas de la
        configuración usada (YAML de renombres y de mapeo, catálogos)."""
        return {"particion_raw": self._particion, "filas_por_hoja": self._filas_entrada,
                "configuracion": huellas_configuracion([self._renombres_yaml, self._mapeo_yaml])}

    # --- Pasos ---------------------------------------------------------------------------------------------------
    def _leer(self) -> dict[str, pd.DataFrame]:
        """Hojas de la partición más reciente. Falla si falta o sobra una hoja: un cambio en la carga histórica debe
        detener la transformación, no propagarse."""
        if self._hojas is not None:
            hojas = dict(self._hojas)
        else:
            self._particion, hojas = leer_particion_reciente(self._raw_dir)
            logger.info(f"[excel] partición {self._particion}: {len(hojas)} hojas")
        faltantes, inesperadas = HOJAS_ESPERADAS - set(hojas), set(hojas) - HOJAS_ESPERADAS
        if faltantes or inesperadas:
            raise ValueError(f"Hojas faltantes: {sorted(faltantes)} | inesperadas: {sorted(inesperadas)}")
        self._filas_entrada = {h: len(df) for h, df in sorted(hojas.items())}
        return hojas

    @staticmethod
    def _balance_de_hoja(hoja: str, filas_entrada: int, salida: dict[str, pd.DataFrame], reporte: ReporteCalidad) -> None:
        """Registra filas de entrada y de salida por tabla. Salvo en las hojas que cambian de grano (laboratorio: filas
        eliminadas y agrupadas por toma, contadas en `correcciones`), las tablas derivadas deben sumar las filas de
        entrada: una diferencia sería una pérdida sin explicación y detiene la corrida."""
        for nombre, df in salida.items():
            reporte.registrar_balance(hoja, filas_entrada, nombre, len(df))
        total = sum(len(df) for df in salida.values())
        if hoja not in HOJAS_QUE_CAMBIAN_DE_GRANO and total != filas_entrada:
            raise ValueError(f"{hoja}: entraron {filas_entrada} filas y salieron {total} sin explicación")

    def _preparar_registro(self, reg: pd.DataFrame, reporte: ReporteCalidad) -> pd.DataFrame:
        """E3 a E8 sobre registro_trauma (las hojas hijas usan sus fechas ya convertidas)."""
        reg = seudonimizar_identidad(reg, self._clave, reporte)
        reg = excluir_columnas(reg, EXCLUIR_DEL_DW, reporte)
        fechas_y_cronologia_registro(reg, reporte)
        reg = edad_a_quinquenio(reg, reporte)
        marcar_duplicados_registro(reg, reporte)
        return reg

    def _finalizar(self, tablas: dict[str, pd.DataFrame], reporte: ReporteCalidad) -> dict[str, pd.DataFrame]:
        """La llave del Excel pasa a `record_id` (lo que espera aplicar_llaves) y se perfila el estado final."""
        finales = {}
        for nombre, df in tablas.items():
            if CLAVE not in df.columns:
                raise KeyError(f"{nombre}: sin la llave {CLAVE}")
            if "record_id" in df.columns:
                raise ValueError(f"{nombre}: ya tiene una columna record_id")
            df = df.rename(columns={CLAVE: "record_id"})
            reporte.perfilar(df, nombre, "despues")
            finales[nombre] = df
        return finales
