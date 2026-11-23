"""Ayudas de las pruebas de calidad sobre la bodega cargada: inyección de defectos y búsqueda de resultados."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from etl.quality.bodega import Resultado

ESQUEMA = "trauma_completo"


def por_regla(resultados: list[Resultado], regla: str, contiene: str = "") -> list[Resultado]:
    """Los resultados de una regla cuyo detalle contiene el texto dado."""
    return [r for r in resultados if r.regla == regla and contiene in r.detalle]


def quitar_restricciones(conexion: Connection, esquema: str, tabla: str, tipos: str) -> list[tuple[str, str]]:
    """
    Elimina las restricciones de la tabla de los tipos dados ('f' claves foráneas, 'u' únicas, 'c' de verificación)
    para poder inyectar un defecto que la base normalmente rechaza. Solo se usa dentro de la transacción de una
    prueba: PostgreSQL revierte también el DDL.

    Returns:
        [(nombre, definición)] de lo eliminado, para volver a crearlo con `restaurar_sin_validar`.
    """
    quitadas = conexion.execute(
        text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
             "WHERE conrelid = to_regclass(:tabla) AND contype::text = ANY(:tipos)"),
        {"tabla": f"{esquema}.{tabla}", "tipos": list(tipos)},
    ).all()
    for nombre, _ in quitadas:
        conexion.execute(text(f'ALTER TABLE {esquema}.{tabla} DROP CONSTRAINT "{nombre}"'))
    return [tuple(q) for q in quitadas]


def restaurar_sin_validar(conexion: Connection, esquema: str, tabla: str, restricciones: list[tuple[str, str]]) -> None:
    """
    Vuelve a crear claves foráneas o de verificación como NOT VALID: la base las conserva (y el verificador las
    encuentra en el catálogo) pero no revisa las filas que ya existen, que son las del defecto inyectado.
    """
    for nombre, definicion in restricciones:
        conexion.execute(text(f'ALTER TABLE {esquema}.{tabla} ADD CONSTRAINT "{nombre}" {definicion} NOT VALID'))


def duplicar_fila(conexion: Connection, esquema: str, tabla: str, donde: str) -> None:
    """Inserta una copia de una fila de la tabla (la primera que cumpla `donde`), sin sus columnas de identidad."""
    columnas = [c["name"] for c in inspect(conexion).get_columns(tabla, schema=esquema) if not c.get("identity")]
    lista = ", ".join(columnas)
    conexion.execute(text(
        f"INSERT INTO {esquema}.{tabla} ({lista}) SELECT {lista} FROM {esquema}.{tabla} WHERE {donde} LIMIT 1"
    ))
