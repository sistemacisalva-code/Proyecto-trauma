# REDCap extractor module
import pandas as pd
import requests
import logging
import redcap
from datetime import datetime
from io import StringIO
from etl.extract.base import BaseExtractor

logger = logging.getLogger(__name__)

class REDCapExtractor(BaseExtractor):

    source_type = "redcap"
    
    """
    Extractor especializado en obtener registros desde la API REST de REDCap.
    """
    
    def __init__(
        self, 
        api_url: str,
        api_token: str, 
        export_fields: list[str] | None = None,
        date_begin: datetime | None = None,
        date_end: datetime | None = None,
    ):
        """
        Args:
            api_url (str): URL del endpoint de la API de REDCap (ej. https://redcap.hospital.org/api/).
            api_token (str): Token de autenticación del proyecto REDCap.
            export_fields (list): Opcional. Lista de variables específicas a exportar.

        Raises:
            ValueError: si api_url o api_token no fueron proporcionados.
        """
        if not api_url or not api_token:
            raise ValueError("La URL de la API y el token de REDCap no pueden ser nulos.")

        self.api_url = api_url
        self.api_token = api_token
        self.export_fields = export_fields
        self.date_begin = date_begin
        self.date_end = date_end
        self._project: redcap.Project | None = None

    def _resolve_project(self) -> redcap.Project:
        """
        Crea (una sola vez) y cachea el cliente `redcap.Project`. Es perezoso: no hay
        llamadas de red hasta el primer `extract()`. El constructor de `redcap.Project`
        hace una llamada de metadata (lectura) que sirve de verificación temprana de URL/token.
        """
        if self._project is None:
            self._project = redcap.Project(self.api_url, self.api_token)
        return self._project

    def extract(self) -> pd.DataFrame:
        """
        Exporta los registros desde REDCap (única operación de PyCap usada: export_records).

        Se pide format_type="json" y se construye el DataFrame a mano, en vez de usar
        format_type="df", por dos razones de la capa raw:
          - "df" pone record_id como índice y save_extraction_result escribe con
            index=False, así que el identificador se perdería (en un proyecto longitudinal
            record_id se repite por evento y la fila solo se distingue con redcap_event_name).
          - "df" convierte tipos (fechas, numéricos) y altera los valores de origen; aquí se
            conservan como texto y los tipos se fijan en Transform.

        DECISIÓN PROVISIONAL: raw_or_label="label" (no "raw"). Los campos de opción única
        (radio/dropdown/checkbox) llegan con la etiqueta de texto (ej. "Masculino"), no con
        el código de REDCap (ej. "1"). Se eligió así momentáneamente por legibilidad; el
        costo es que si el diccionario de variables cambia el texto de una opción en REDCap,
        los registros ya extraídos con la etiqueta anterior no se actualizan solos, y quedan
        dos textos distintos para el mismo código a través del tiempo. Revertir a "raw" (más
        estable, delega la traducción código->etiqueta a Transform vía export_metadata) si
        ese riesgo se vuelve un problema real.

        Returns:
            pd.DataFrame: una fila por registro-evento, con record_id como columna y los
                valores en texto (etiquetas, no códigos; ver nota de raw_or_label arriba).
                Vacío (sin columnas) si REDCap no devuelve registros.

        Raises:
            Exception: cualquier error propagado por PyCap (token inválido, sin permiso,
                variables inexistentes, red caída, etc.).
        """
        logger.info(f"Iniciando extraccion desde la API de REDCap en: {self.api_url}")

        try:
            project = self._resolve_project()
            registros = project.export_records(
                fields=self.export_fields,
                date_begin=self.date_begin,
                date_end=self.date_end,
                format_type="json",
                raw_or_label = "label",
            )
            df = pd.DataFrame(registros)
            if "redcap_repeat_instance" in df.columns:
                # REDCap devuelve este campo interno como "" (sin repetición) o
                # como int (con repetición): esa mezcla de tipos en la misma
                # columna rompe la escritura a Parquet (pyarrow exige un tipo
                # único por columna). Se uniforma a texto, igual que el resto
                # de los valores crudos, sin interpretar el dato.
                df["redcap_repeat_instance"] = df["redcap_repeat_instance"].astype(str)
        except Exception as e:
            logger.error(f"Error al exportar registros desde REDCap: {e}")
            raise e

        logger.info(f"Extraccion exitosa de REDCap. Registros obtenidos: {len(df)}")
        return df        