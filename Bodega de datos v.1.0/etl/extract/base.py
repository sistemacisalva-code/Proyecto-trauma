# Base extractor module
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """
    Encapsula el DataFrame extraído junto con su metadata de trazabilidad,
    necesaria para el registro de calidad de datos y la escritura en data/raw.
    """
    data: pd.DataFrame
    source_type: str
    rows: int
    elapsed_seconds: float
    extracted_at: str


class BaseExtractor(ABC):
    """
    Clase abstracta base que define la interfaz común para todos los
    mecanismos de extracción de datos del proyecto.

    Implementa el patrón Template Method: `run()` estandariza logging,
    medición de tiempo y metadata de trazabilidad para todos los extractores;
    cada subclase solo implementa la lógica específica en `extract()`.
    """

    source_type: str = "unknown"

    @abstractmethod
    def extract(self) -> pd.DataFrame:
        """
        Realiza la extracción de datos desde el origen configurado y
        retorna un DataFrame de Pandas estructurado para la etapa de transformación.

        Returns:
            pd.DataFrame: Los datos crudos extraídos del origen.
        """
        raise NotImplementedError

    def run(self) -> ExtractionResult:
        """
        Ejecuta `extract()` con logging y metadata estandarizados.
        Los extractores concretos y el pipeline deben invocar este método
        en vez de llamar a `extract()` directamente.
        """
        start = time.perf_counter()
        logger.info(f"[{self.source_type}] Iniciando extracción")

        df = self.extract()

        elapsed = time.perf_counter() - start
        logger.info(
            f"[{self.source_type}] Extracción completa: {len(df)} filas en {elapsed:.2f}s"
        )

        return ExtractionResult(
            data=df,
            source_type=self.source_type,
            rows=len(df),
            elapsed_seconds=round(elapsed, 3),
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )