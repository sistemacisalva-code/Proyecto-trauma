"""Piezas compartidas por las verificaciones de calidad de la bodega cargada (`bodega.py` y `valores.py`)."""
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from etl.load.warehouse.contrato import Contrato


@dataclass(frozen=True)
class Resultado:
    """Resultado de una verificación: cuántas filas se evaluaron y cuántas incumplen la regla (la meta es 0)."""
    regla: str
    detalle: str
    evaluadas: int
    incumplen: int

    @property
    def cumple(self) -> bool:
        return self.incumplen == 0


def esquema_de(contrato: Contrato) -> str:
    """Esquema del modelo en la bodega: trauma_<modelo> (misma convención que main.py)."""
    return f"trauma_{contrato.modelo}"


def hecho_de(contrato: Contrato) -> tuple[str, dict]:
    """Nombre y definición de la única tabla de hechos del contrato."""
    (nombre,) = [t for t, d in contrato.tablas.items() if d["tipo"] == "hecho"]
    return nombre, contrato.tablas[nombre]


def tabla_de(conexion: Connection, esquema: str, nombre: str) -> str:
    """Nombre calificado y entrecomillado de una tabla, para armar las consultas."""
    comillas = conexion.dialect.identifier_preparer
    return f"{comillas.quote_schema(esquema)}.{comillas.quote(nombre)}"


def columna_de(conexion: Connection, nombre: str) -> str:
    """Nombre de columna entrecomillado, para armar las consultas."""
    return conexion.dialect.identifier_preparer.quote(nombre)


def ultimas_cargas(conexion: Connection, modelo: str) -> dict[str, int]:
    """La última carga exitosa de cada fuente del modelo en etl_control.carga: {fuente: id de la carga}."""
    filas = conexion.execute(
        text("SELECT DISTINCT ON (fuente) fuente, id FROM etl_control.carga "
             "WHERE modelo = :modelo AND exitosa ORDER BY fuente, id DESC"),
        {"modelo": modelo},
    ).all()
    return dict(filas)
