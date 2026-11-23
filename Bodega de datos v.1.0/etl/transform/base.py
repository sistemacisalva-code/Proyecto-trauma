# Base transform module
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import time

import pandas as pd

from etl.transform.common.duplicados_negocio import retirar_atenciones_duplicadas
from etl.transform.common.keys import aplicar_llaves
from etl.transform.common.procedencia import version_codigo
from etl.transform.common.quality import ReporteCalidad

logger = logging.getLogger(__name__)


@dataclass
class TransformResult:
    """
    Encapsula las tablas transformadas junto con su reporte de calidad y su metadata de
    trazabilidad, necesarios para la escritura en data/staging.
    """
    tables: dict[str, pd.DataFrame]
    reporte: ReporteCalidad
    source_type: str
    rows: dict[str, int]
    elapsed_seconds: float
    transformed_at: str
    procedencia: dict = field(default_factory=dict)   # entrada leída, versión del código y huellas de configuración


class BaseTransformer(ABC):
    """
    Clase abstracta base que define la interfaz común para todos los transformadores de datos.

    Implementa el patrón Template Method: `run()` estandariza logging, medición de tiempo,
    verificación de la auditoría de conservación y namespacing de llaves; cada subclase solo implementa
    `transform()` y declara de qué fuente viene y cuál es su tabla de grano episodio.
    """

    source_type: str = "unknown"
    source_system: str = "unknown"   # prefijo de llave en common/keys.py (p. ej. "redcap")
    tabla_base: str = ""             # tabla de grano episodio; las demás se enlazan a ella
    # Columnas de la tabla base que, repetidas, identifican la misma llegada (documento y fecha y hora de llegada);
    # None = la fuente no retira atenciones duplicadas. Ver common/duplicados_negocio.py
    columnas_duplicado_negocio: tuple[str, ...] | None = None

    @abstractmethod
    def transform(self, reporte: ReporteCalidad) -> dict[str, pd.DataFrame]:
        """
        Lee los datos extraídos en data/raw y devuelve un DataFrame por tabla, cada uno con la
        columna `record_id` (la llave de la fuente). Registra en `reporte` todo lo que haga.
        """
        raise NotImplementedError

    def procedencia(self) -> dict:
        """Qué entrada leyó la última transformación y qué archivos de configuración usó (solo nombres, conteos y
        huellas). Cada subclase la completa; `run()` le agrega la versión del código."""
        return {}

    def run(self) -> TransformResult:
        """
        Ejecuta `transform()` y completa la salida: verifica que ninguna variable perdió datos sin
        explicación y reemplaza `record_id` por las llaves del esquema canónico. El pipeline debe
        invocar este método y no `transform()` directamente.
        """
        start = time.perf_counter()
        logger.info(f"[{self.source_type}] Iniciando transformación")

        reporte = ReporteCalidad()
        tablas = self.transform(reporte)
        reporte.verificar_auditoria()
        tablas = aplicar_llaves(tablas, self.source_system, self.tabla_base, reporte)
        if self.columnas_duplicado_negocio:
            tablas = retirar_atenciones_duplicadas(tablas, self.tabla_base, self.columnas_duplicado_negocio, reporte)

        elapsed = time.perf_counter() - start
        logger.info(f"[{self.source_type}] Transformación completa: {len(tablas)} tablas en {elapsed:.2f}s")

        return TransformResult(
            tables=tablas,
            reporte=reporte,
            source_type=self.source_type,
            rows={nombre: len(df) for nombre, df in tablas.items()},
            elapsed_seconds=round(elapsed, 3),
            transformed_at=datetime.now(timezone.utc).isoformat(),
            procedencia={**self.procedencia(), "codigo": version_codigo()},
        )
