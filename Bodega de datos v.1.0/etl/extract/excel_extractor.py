# Excel extractor module
import os

import pandas as pd
import logging
from etl.extract.base import BaseExtractor

logger = logging.getLogger(__name__)

class ExcelExtractor(BaseExtractor):

    """
    Extractor especializado en archivos de Microsoft Excel.
    """

    source_type = "excel"

    def __init__(self, source, sheet_name: str = 0, engine="calamine"):
        """
        Args:
            source (str | pd.ExcelFile): ruta al archivo Excel, o un pd.ExcelFile ya
                abierto y compartido entre varios extractores (evita reabrir/reparsear
                el mismo workbook para cada hoja).
            sheet_name (str/int): nombre o índice de la hoja a extraer. Por defecto la primera (0).
            engine (str): motor de lectura usado si `source` es una ruta nueva a abrir
                ("calamine" recomendado por velocidad; ignorado si `source` ya es un pd.ExcelFile).

        Raises:
            TypeError: si `source` no es ni str ni pd.ExcelFile.
        """

        self.sheet_name = sheet_name
        self.engine = engine

        if isinstance(source, str):
            self._file_path = source
            self._excel_file = None
            self._owns_handle = True

        elif isinstance(source, pd.ExcelFile):
            self._excel_file = source
            self._file_path = None
            self._owns_handle = False
        else:
            raise TypeError(f"'source' debe ser str o pd.Excelfile, recibido: {type(source)}")


    def _resolve_excel_file(self) -> pd.ExcelFile:
        """
        Retorna el pd.ExcelFile a usar: si vino inyectado (workbook compartido), lo
        reutiliza tal cual; si `source` fue una ruta, lo abre (una sola vez) y lo
        cachea en self._excel_file para no reparsear el archivo en llamadas futuras.

        Raises:
            FileNotFoundError: si la ruta configurada no existe en disco.
        """
        if self._excel_file is not None:
            return self._excel_file
        if os.path.exists(self._file_path) is False:
            raise FileNotFoundError(f"El archivo Excel no fue encontrado: {self._file_path}")
        self._excel_file = pd.ExcelFile(self._file_path, engine=self.engine)
        return self._excel_file

    @staticmethod
    def list_sheets(file_path, engine="calamine") -> list:
        """
        Abre el workbook solo para listar los nombres de hoja disponibles,
        sin parsear datos de ninguna hoja. Útil para validar configuración
        (ver `validate_configured_sheets`) antes de correr la extracción real.

        Args:
            file_path (str): ruta al archivo Excel.
            engine (str): motor de lectura ("calamine" por defecto).

        Returns:
            list: nombres de las hojas del workbook, en orden.

        Raises:
            FileNotFoundError: si el archivo no existe en disco.
        """
        if os.path.exists(file_path) is False:
            raise FileNotFoundError(f"El archivo Excel no fue encontrado: {file_path}")
        else:
            with pd.ExcelFile(file_path, engine=engine) as excel_file:
                return excel_file.sheet_names

    @classmethod
    def validate_configured_sheets(cls, file_path, sheets_config, engine="calamine") -> None:
        """
        Verifica en modo fail-fast que todas las hojas declaradas en `sheets_config`
        existan realmente en el workbook, antes de procesar ninguna. Detecta a tiempo
        un renombre de hoja en el archivo fuente (ej. el hospital cambia el nombre
        de una pestaña) en vez de fallar a mitad de la extracción.

        Args:
            file_path (str): ruta al archivo Excel a validar.
            sheets_config (dict): equivalente a EXCEL_SHEETS_CONFIG de config/settings.py;
                cada valor debe tener la clave "sheet_name" con el nombre real esperado.
            engine (str): motor de lectura ("calamine" por defecto).

        Raises:
            ValueError: si alguna hoja configurada no existe en el archivo real.
        """
        hojas_reales = cls.list_sheets(file_path, engine=engine)
        hojas_esperadas = [cfg["sheet_name"] for cfg in sheets_config.values()]
        faltantes = [h for h in hojas_esperadas if h not in hojas_reales]
        if faltantes:
            raise ValueError(
                f"Hojas configuradas en settings.py no encontradas en el archivo: {faltantes}. "
                f"Hojas disponibles en el workbook: {hojas_reales}"
            )

    def extract(self) -> pd.DataFrame:
        """
        Extrae la hoja configurada (self.sheet_name) del workbook resuelto por
        _resolve_excel_file(). Si el handle fue abierto por esta instancia
        (source era una ruta), lo cierra al terminar; si fue compartido desde
        afuera, lo deja abierto para que otros extractores lo sigan usando.

        Returns:
            pd.DataFrame: datos crudos de la hoja, sin transformar.

        Raises:
            FileNotFoundError: si el archivo no existe (propagado desde _resolve_excel_file).
            ValueError: si self.sheet_name no existe en el workbook.
        """
        origen = self._file_path or "workbook compartido"
        logger.info(f"Iniciando extracción desde Excel: {origen} (Hoja: {self.sheet_name})")

        excel_file = self._resolve_excel_file()

        if self.sheet_name not in excel_file.sheet_names:
            raise ValueError (f"Hoja '{self.sheet_name}' no existe")
        try:
            df = excel_file.parse(sheet_name=self.sheet_name)
        except Exception as e:
            logger.error(f"Se presento un error con la hoja del archivo: {e}"); raise e

        if self._owns_handle:
            excel_file.close()
        return df

