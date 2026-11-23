# Base load module
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import time

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from etl.load.warehouse.contrato import FUENTES, Contrato, leer_contrato
from etl.load.warehouse.cuarentena import escribir_cuarentena
from etl.load.warehouse.staging import esquema_staging, leer_manifiesto, leer_tablas

logger = logging.getLogger(__name__)

# El Excel es histórico: se carga una vez por modelo y repetirlo exige force
FUENTE_HISTORICA = "excel"

# Motivos por los que una fila leída no se carga sin ser un error; los errores van a la cuarentena
MOTIVOS_NO_USADAS = ("otra_toma", "sin_valor", "duplicado")

# Conteos de atenciones de la carga incremental; van a etl_control.carga como atenciones_<nombre>
CONTEOS_ATENCIONES = ("nuevas", "modificadas", "sin_cambio", "eliminadas")

# Un uso es (destino, tabla de staging): el hecho con cada tabla que lo alimenta, o un bloque de puente con su
# tabla de filas. El destino de un puente por rol se escribe "tabla[rol]", como en Contrato.bloques()
Uso = tuple[str, str]


@dataclass
class LoadResult:
    """
    Resume una carga: de qué corrida del staging salió, cuántas filas se leyeron y apartaron por tabla de staging,
    el balance de cada uso (leídas, cargadas, no usadas por motivo y cuarentena) y, si la carga es incremental, las
    atenciones nuevas, modificadas, sin cambio y eliminadas. Solo conteos, nunca datos.
    """
    modelo: str
    fuente: str
    run_id_staging: str
    filas_origen: dict[str, int]
    filas_cuarentena: dict[str, int]
    detalle: dict[Uso, dict[str, int]]
    elapsed_seconds: float
    loaded_at: str
    ruta_cuarentena: str | None = None
    atenciones: dict[str, int] = field(default_factory=dict)   # claves de CONTEOS_ATENCIONES; vacío = no incremental

    def totales(self) -> dict[str, int]:
        """
        Sumas como las guarda etl_control.carga: sobre los usos en una carga exitosa; en una fallida (sin detalle),
        las filas leídas y apartadas del staging.
        """
        if not self.detalle:
            return {"filas_origen": sum(self.filas_origen.values()), "filas_cargadas": 0, "filas_no_usadas": 0,
                    "filas_cuarentena": sum(self.filas_cuarentena.values())}
        usos = self.detalle.values()
        return {
            "filas_origen": sum(u["leidas"] for u in usos),
            "filas_cargadas": sum(u["cargadas"] for u in usos),
            "filas_no_usadas": sum(u[m] for u in usos for m in MOTIVOS_NO_USADAS),
            "filas_cuarentena": sum(u["cuarentena"] for u in usos),
        }


def reconciliar(origen: dict[str, int], usos: dict[Uso, dict[str, int]],
                cuarentena: dict[str, int]) -> dict[Uso, dict[str, int]]:
    """
    Regla QR-EXA-01 en el propio pipeline: una carga que pierde filas sin explicación no llega a Power BI. Se
    cuadra por uso porque una tabla de staging puede alimentar varios destinos: en cada uso, filas leídas de su tabla =
    cargadas + otra_toma + sin_valor + duplicado + cuarentena. Leídas y cuarentena son las de la tabla de staging:
    una fila apartada no llega a ningún uso. Además, toda tabla leída tiene al menos un uso y todo uso es de una
    tabla leída (el Loader no cuenta donde no debe ni deja tablas sin explicar).

    Args:
        usos: lo que devuelve `cargar()`: {(destino, tabla): {"cargadas": n, <motivo>: n, ...}}; un motivo
              ausente vale 0.

    Returns:
        El balance completo de cada uso, para el resultado y etl_control.carga_detalle.

    Raises:
        ValueError: con cada uso que no cuadra o trae un motivo desconocido, y cada tabla leída sin uso.
    """
    detalle, descuadres = {}, {}
    for (destino, tabla), conteo in sorted(usos.items()):
        balance = {"leidas": origen.get(tabla, 0), "cargadas": conteo.get("cargadas", 0),
                   **{m: conteo.get(m, 0) for m in MOTIVOS_NO_USADAS}, "cuarentena": cuarentena.get(tabla, 0)}
        explicadas = balance["cargadas"] + sum(balance[m] for m in MOTIVOS_NO_USADAS) + balance["cuarentena"]
        desconocidos = sorted(set(conteo) - {"cargadas", *MOTIVOS_NO_USADAS})
        if tabla not in origen or desconocidos or balance["leidas"] != explicadas:
            descuadres[f"{destino} <- {tabla}"] = {**balance, **({"desconocidos": desconocidos} if desconocidos else {})}
        detalle[(destino, tabla)] = balance
    sin_uso = sorted(set(origen) - {tabla for _, tabla in usos})
    if descuadres or sin_uso:
        raise ValueError(
            "La carga no reconcilia (leídas = cargadas + otra_toma + sin_valor + duplicado + cuarentena): "
            f"{descuadres}" + (f"; tablas leídas sin uso: {sin_uso}" if sin_uso else "")
        )
    return detalle


class BaseLoader(ABC):
    """
    Clase abstracta base de la carga del staging de una fuente a un modelo de la bodega. Entre modelos cambia el
    destino, no la fuente: los pasos comunes quedan aquí y cada modelo solo declara lo suyo.

    Implementa el patrón Template Method: `run()` fija el orden de los pasos comunes (contrato, manifiesto,
    validación, guardia del Excel, lectura, cuarentena, transacción, reconciliación y registro de la corrida);
    cada modelo implementa `cargar()` con sus tablas y, si lo necesita, `separar_cuarentena()`.
    """

    modelo: str = "unknown"

    def __init__(self, fuente: str, engine: Engine, staging_dir: str, ruta_contrato: str,
                 quarantine_dir: str, force: bool = False, refresco_completo: bool = False):
        """`force` repite la carga del Excel. `refresco_completo` reescribe todas las atenciones de la
        fuente en vez de solo las que cambiaron; `cargar()` deja en `atenciones` lo que hizo."""
        if fuente not in FUENTES:
            raise ValueError(f"Fuente desconocida: '{fuente}'. Disponibles: {list(FUENTES)}")
        self.fuente = fuente
        self.engine = engine
        self.staging_dir = staging_dir
        self.ruta_contrato = ruta_contrato
        self.quarantine_dir = quarantine_dir
        self.force = force
        self.refresco_completo = refresco_completo
        self.atenciones: dict[str, int] = {}

    def separar_cuarentena(self, tablas: dict[str, pd.DataFrame], contrato: Contrato
                           ) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
        """
        Aparta las filas que no pueden entrar a la bodega. Devuelve (tablas a cargar, cuarentena por tabla);
        cada fila en cuarentena lleva su regla en `regla_cuarentena`. Por defecto no aparta nada.
        """
        return tablas, {}

    @abstractmethod
    def cargar(self, conexion: Connection, tablas: dict[str, pd.DataFrame], contrato: Contrato
               ) -> dict[Uso, dict[str, int]]:
        """
        Escribe el modelo dentro de la transacción que abre `run()`: dimensiones, borrado de la fuente, hechos,
        puentes y limpieza. No hace COMMIT ni ROLLBACK.

        Returns:
            dict: por uso (destino, tabla de staging), las filas cargadas y las no usadas por motivo
                  (MOTIVOS_NO_USADAS), para la reconciliación.
        """
        raise NotImplementedError

    def run(self) -> LoadResult:
        """
        Ejecuta la carga completa. Todo lo que puede fallar sin tocar la base (contrato, manifiesto, columnas del
        staging) se comprueba antes de abrir una conexión. El pipeline debe invocar este método y no `cargar()`.
        """
        start = time.perf_counter()
        logger.info(f"[{self.modelo}/{self.fuente}] Iniciando carga")

        # 1-3. Contrato, manifiesto y validación del contrato contra el esquema del staging (sin conexión)
        contrato = leer_contrato(self.ruta_contrato, self.modelo)
        manifiesto = leer_manifiesto(self.staging_dir)
        if manifiesto["source_type"] != self.fuente:
            raise ValueError(
                f"El staging de '{self.staging_dir}' es de '{manifiesto['source_type']}', no de '{self.fuente}'"
            )
        columnas = contrato.columnas_por_tabla(self.fuente)
        contrato.validar_contra(esquema_staging(self.staging_dir, list(columnas)), self.fuente)

        # 4. Guardia del Excel: primera consulta a la base
        if self.fuente == FUENTE_HISTORICA and not self.force and self._existe_carga_exitosa():
            raise RuntimeError(
                f"El Excel ya se cargó en el modelo '{self.modelo}'. Si cambió su staging, use --force."
            )

        # 5-6. Solo las columnas del contrato; la cuarentena se escribe antes de la transacción para que ninguna
        # fila contada en ella falte en disco
        tablas = leer_tablas(self.staging_dir, columnas)
        filas_origen = {tabla: len(df) for tabla, df in tablas.items()}
        tablas, cuarentena = self.separar_cuarentena(tablas, contrato)
        filas_cuarentena = {tabla: len(df) for tabla, df in cuarentena.items() if not df.empty}
        loaded_at = datetime.now(timezone.utc)
        ruta_cuarentena = escribir_cuarentena(cuarentena, self.quarantine_dir, self.modelo, self.fuente,
                                              loaded_at.strftime("%Y-%m-%dT%H%M%S"))

        # 7-9. Una transacción: o queda la carga completa y su registro, o la bodega queda como estaba
        try:
            with self.engine.begin() as conexion:
                self.atenciones = {}
                usos = self.cargar(conexion, tablas, contrato)
                detalle = reconciliar(filas_origen, usos, filas_cuarentena)
                resultado = LoadResult(
                    modelo=self.modelo, fuente=self.fuente, run_id_staging=manifiesto["run_id"],
                    filas_origen=filas_origen, filas_cuarentena=filas_cuarentena, detalle=detalle,
                    elapsed_seconds=0.0, loaded_at=loaded_at.isoformat(), ruta_cuarentena=ruta_cuarentena,
                    atenciones=dict(self.atenciones),
                )
                self._registrar_carga(conexion, resultado, exitosa=True)
        except Exception:
            self._registrar_falla(manifiesto["run_id"], filas_origen, filas_cuarentena, ruta_cuarentena)
            raise

        resultado.elapsed_seconds = round(time.perf_counter() - start, 3)
        totales = resultado.totales()
        logger.info(
            f"[{self.modelo}/{self.fuente}] Carga completa: de {totales['filas_origen']} filas por uso, "
            f"{totales['filas_cargadas']} cargadas, {totales['filas_no_usadas']} no usadas y "
            f"{totales['filas_cuarentena']} en cuarentena en {resultado.elapsed_seconds:.2f}s"
        )
        return resultado

    # -----------------------------------------------------------------------
    # etl_control.carga
    # -----------------------------------------------------------------------

    def _existe_carga_exitosa(self) -> bool:
        with self.engine.connect() as conexion:
            return conexion.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM etl_control.carga "
                    "WHERE modelo = :modelo AND fuente = :fuente AND exitosa)"
                ),
                {"modelo": self.modelo, "fuente": self.fuente},
            ).scalar()

    def _registrar_carga(self, conexion: Connection, resultado: LoadResult, exitosa: bool) -> None:
        """La corrida en etl_control.carga y, si tiene, su balance por uso en etl_control.carga_detalle."""
        carga_id = conexion.execute(
            text(
                "INSERT INTO etl_control.carga (modelo, fuente, run_id_staging, filas_origen, filas_cargadas, "
                "filas_no_usadas, filas_cuarentena, atenciones_nuevas, atenciones_modificadas, "
                "atenciones_sin_cambio, atenciones_eliminadas, ruta_cuarentena, exitosa) "
                "VALUES (:modelo, :fuente, :run_id_staging, :filas_origen, :filas_cargadas, :filas_no_usadas, "
                ":filas_cuarentena, :atenciones_nuevas, :atenciones_modificadas, :atenciones_sin_cambio, "
                ":atenciones_eliminadas, :ruta_cuarentena, :exitosa) RETURNING id"
            ),
            {"modelo": resultado.modelo, "fuente": resultado.fuente, "run_id_staging": resultado.run_id_staging,
             **resultado.totales(), **{f"atenciones_{c}": resultado.atenciones.get(c, 0) for c in CONTEOS_ATENCIONES},
             "ruta_cuarentena": resultado.ruta_cuarentena, "exitosa": exitosa},
        ).scalar()
        if resultado.detalle:
            conexion.execute(
                text(
                    "INSERT INTO etl_control.carga_detalle (carga_id, destino, tabla_staging, leidas, cargadas, "
                    "otra_toma, sin_valor, duplicado, cuarentena) "
                    "VALUES (:carga_id, :destino, :tabla_staging, :leidas, :cargadas, :otra_toma, :sin_valor, "
                    ":duplicado, :cuarentena)"
                ),
                [{"carga_id": carga_id, "destino": destino, "tabla_staging": tabla, **balance}
                 for (destino, tabla), balance in resultado.detalle.items()],
            )

    def _registrar_falla(self, run_id_staging: str, filas_origen: dict[str, int],
                         filas_cuarentena: dict[str, int], ruta_cuarentena: str | None = None) -> None:
        """
        Deja constancia de la carga fallida en una transacción aparte (la de la carga ya se revirtió). Si tampoco
        se puede registrar, solo se informa: el error que importa es el original, que `run()` vuelve a lanzar.
        """
        fallida = LoadResult(
            modelo=self.modelo, fuente=self.fuente, run_id_staging=run_id_staging, filas_origen=filas_origen,
            filas_cuarentena=filas_cuarentena, detalle={}, elapsed_seconds=0.0,
            loaded_at=datetime.now(timezone.utc).isoformat(), ruta_cuarentena=ruta_cuarentena,
        )
        try:
            with self.engine.begin() as conexion:
                self._registrar_carga(conexion, fallida, exitosa=False)
        except Exception:
            logger.exception(f"[{self.modelo}/{self.fuente}] No se pudo registrar la carga fallida")
