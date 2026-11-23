"""
Reporte de calidad de la bodega cargada.

Reúne los resultados de `etl.quality.bodega` con la bitácora de la última carga exitosa de cada fuente y los escribe en
un Markdown legible y en un CSV por sección. Solo contiene conteos, porcentajes y nombres de tablas: nunca filas,
identificadores ni valores de pacientes, así que se puede compartir.
"""
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

from config.settings import QUALITY_REPORTS_BASE_DIR
from etl.load.warehouse.contrato import Contrato
from etl.quality.bodega import Resultado, verificar_bodega

# Dimensión de calidad según el código central del ID de la regla (QR-<código>-<número>)
DIMENSIONES = {
    "INT": "Integridad", "TIE": "Integridad", "DUP": "Unicidad", "EXA": "Exactitud", "NUL": "Completitud",
    "DOM": "Validez", "CON": "Consistencia", "SEG": "Seguridad", "TRZ": "Trazabilidad",
}
# Acción de las reglas que no bloquean (catálogo en docs/tecnico/04_reglas_de_calidad.md); el resto falla.
# QR-NUL-02 y QR-DOM-03 solo informan: no hay umbrales de porcentaje y el veredicto sale de la acción de cada regla
ACCIONES = {
    "QR-DOM-02": "advierte", "QR-DOM-04": "advierte", "QR-CON-01": "advierte", "QR-CON-02": "advierte",
    "QR-CON-04": "advierte",
    "QR-CON-05": "advierte", "QR-CON-06": "advierte",
    "QR-NUL-04": "advierte", "QR-NUL-02": "informa", "QR-NUL-03": "informa", "QR-DOM-03": "informa",
}
# Una verificación por columna: va al detalle de completitud y no a la tabla de reglas ni al resumen
POR_COLUMNA = {"QR-NUL-02"}
# QR-EXA-03 cuenta una diferencia, no un subconjunto de las evaluadas: su porcentaje no tiene sentido
SIN_PORCENTAJE = {"QR-EXA-03"}
USOS_CON_NOVEDAD = ("otra_toma", "sin_valor", "duplicado", "cuarentena")
ARCHIVOS = ("reporte.md", "resumen.csv", "reglas.csv", "reconciliacion.csv", "completitud.csv")
COLUMNAS_EN_EL_REPORTE = 15


@dataclass(frozen=True)
class Carga:
    """Una carga exitosa de la bitácora (etl_control.carga): solo conteos y el run_id del staging de donde salió."""
    id: int
    fuente: str
    run_id_staging: str
    ejecutado_en: datetime
    filas_origen: int
    filas_cargadas: int
    filas_no_usadas: int
    filas_cuarentena: int


def dimension(regla: str) -> str:
    return DIMENSIONES[regla.split("-")[1]]


def estado(resultado: Resultado) -> str:
    """Cumple, o lo que corresponde a la acción de su regla: Falla, Advierte o Informa."""
    if resultado.cumple:
        return "Cumple"
    return {"falla": "Falla", "advierte": "Advierte", "informa": "Informa"}[ACCIONES.get(resultado.regla, "falla")]


def porcentaje(resultado: Resultado) -> str:
    """Incumplen sobre evaluadas, o '—' si la regla no lo admite o no hay filas evaluadas."""
    if resultado.regla in SIN_PORCENTAJE or resultado.evaluadas == 0:
        return "—"
    return f"{100 * resultado.incumplen / resultado.evaluadas:.2f} %"


def _celda(valor) -> str:
    return str(valor).replace("|", "\\|")


def _tabla(encabezados: list[str], filas: list[list]) -> str:
    lineas = ["| " + " | ".join(encabezados) + " |", "|" + "|".join("---" for _ in encabezados) + "|"]
    lineas += ["| " + " | ".join(_celda(c) for c in fila) + " |" for fila in filas]
    return "\n".join(lineas)


@dataclass(frozen=True)
class Reporte:
    """Resultados de las verificaciones y bitácora de las cargas verificadas de un modelo."""
    modelo: str
    generado_en: datetime
    cargas: list[Carga]
    detalle: list[dict]
    resultados: list[Resultado]

    def _verificaciones(self) -> list[Resultado]:
        return [r for r in self.resultados if r.regla not in POR_COLUMNA]

    def veredicto(self) -> str:
        """Rechazada si alguna regla que bloquea incumple; con advertencias si solo incumplen las que advierten."""
        estados = {estado(r) for r in self._verificaciones()}
        if "Falla" in estados:
            return "Rechazada"
        if "Advierte" in estados:
            return "Aprobada con advertencias"
        return "Aprobada"

    def resumen(self) -> list[dict]:
        """Por dimensión de calidad: verificaciones que cumplen, advierten (o solo informan) y fallan."""
        filas: dict[str, dict] = {}
        for r in self._verificaciones():
            fila = filas.setdefault(dimension(r.regla), {"dimension": dimension(r.regla), "cumplen": 0,
                                                         "advierten": 0, "fallan": 0})
            e = estado(r)
            fila["cumplen" if e == "Cumple" else "fallan" if e == "Falla" else "advierten"] += 1
        return list(filas.values())

    def reglas(self) -> list[dict]:
        return [{"regla": r.regla, "dimension": dimension(r.regla), "verificacion": r.detalle,
                 "evaluadas": r.evaluadas, "incumplen": r.incumplen, "porcentaje": porcentaje(r),
                 "estado": estado(r)} for r in self._verificaciones()]

    def completitud(self) -> list[dict]:
        """Vacíos de cada columna del hecho (QR-NUL-02), de mayor a menor porcentaje; solo informa."""
        filas = [{"columna": r.detalle, "filas": r.evaluadas, "vacias": r.incumplen, "porcentaje": porcentaje(r)}
                 for r in self.resultados if r.regla in POR_COLUMNA]
        return sorted(filas, key=lambda f: f["vacias"] / f["filas"] if f["filas"] else 0, reverse=True)

    def a_markdown(self) -> str:
        usos = [d for d in self.detalle if any(d[m] for m in USOS_CON_NOVEDAD)]
        completitud = self.completitud()
        cargas = [[c.id, c.fuente, c.run_id_staging, c.ejecutado_en.strftime("%Y-%m-%d %H:%M"), c.filas_origen,
                   c.filas_cargadas, c.filas_no_usadas, c.filas_cuarentena] for c in self.cargas]
        if len(self.cargas) > 1:
            cargas.append(["—", "Total", "—", "—", *(sum(getattr(c, campo) for c in self.cargas) for campo in (
                "filas_origen", "filas_cargadas", "filas_no_usadas", "filas_cuarentena"))])
        return "\n\n".join([
            f"# Reporte de calidad de la bodega cargada: {self.modelo}",
            f"Generado: {self.generado_en.strftime('%Y-%m-%d %H:%M')} · Veredicto: **{self.veredicto()}**",
            "Solo contiene conteos y porcentajes; nunca filas ni valores de pacientes.",
            "## 1. Cargas verificadas\nLa última carga exitosa de cada fuente y el total de las fuentes.",
            _tabla(["Carga", "Fuente", "Staging (run_id)", "Ejecutada", "Leídas", "Cargadas", "No usadas",
                    "Cuarentena"], cargas) if cargas else "No hay cargas exitosas en la bitácora.",
            "## 2. Resumen por dimensión de calidad",
            _tabla(["Dimensión", "Cumplen", "Advierten", "Fallan"],
                   [[f["dimension"], f["cumplen"], f["advierten"], f["fallan"]] for f in self.resumen()]),
            "## 3. Reglas\n`Incumplen` es la cantidad de filas (o usos, o diferencia de filas) que no cumple la regla; "
            "el catálogo de reglas está en `docs/tecnico/04_reglas_de_calidad.md`.",
            _tabla(["Regla", "Dimensión", "Verificación", "Evaluadas", "Incumplen", "%", "Estado"],
                   [[r["regla"], r["dimension"], r["verificacion"], r["evaluadas"], r["incumplen"], r["porcentaje"],
                     r["estado"]] for r in self.reglas()]),
            "## 4. Reconciliación por uso\nEl balance completo de cada uso está en `reconciliacion.csv`. Aquí, los usos "
            "con filas no usadas o en cuarentena.",
            _tabla(["Carga", "Destino", "Tabla de staging", "Leídas", "Cargadas", "Otra toma", "Sin valor", "Duplicado",
                    "Cuarentena"],
                   [[d["carga_id"], d["destino"], d["tabla_staging"], d["leidas"], d["cargadas"], d["otra_toma"],
                     d["sin_valor"], d["duplicado"], d["cuarentena"]] for d in usos])
            if usos else "Ningún uso tiene filas no usadas ni en cuarentena.",
            "## 5. Completitud por columna (informativa)\nFilas vacías de cada columna del hecho y de los atributos de sus "
            f"dimensiones (`Sin dato`), sin umbral. Aquí las {COLUMNAS_EN_EL_REPORTE} con más vacíos; el total está en "
            "`completitud.csv`.",
            _tabla(["Columna", "Filas", "Vacías", "%"],
                   [[c["columna"], c["filas"], c["vacias"], c["porcentaje"]]
                    for c in completitud[:COLUMNAS_EN_EL_REPORTE]]) if completitud else "No hay filas en el hecho.",
            "## 6. Pendiente en esta versión\n"
            + ("Aún no se generan los indicadores."
               if any(r.regla == "QR-DOM-04" for r in self.resultados) else
               "No se evaluó QR-DOM-04 (falta `config/valores_permitidos.yaml`) y aún no se generan los indicadores."),
        ]) + "\n"

    def escribir(self, base: str = QUALITY_REPORTS_BASE_DIR) -> Path:
        """
        Escribe el reporte en `<base>/warehouse/<modelo>/carga_id=<la más reciente>/` (o `sin_carga` si la bitácora no
        tiene cargas exitosas) y devuelve esa carpeta.
        """
        ultima = max((c.id for c in self.cargas), default=None)
        carpeta = Path(base) / "warehouse" / self.modelo / f"carga_id={ultima if ultima is not None else 'sin_carga'}"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "reporte.md").write_text(self.a_markdown(), encoding="utf-8")
        resumen, reglas = self.resumen(), self.reglas()
        _csv(carpeta / "resumen.csv", ["dimension", "cumplen", "advierten", "fallan"], resumen)
        _csv(carpeta / "reglas.csv", ["regla", "dimension", "verificacion", "evaluadas", "incumplen", "porcentaje",
                                      "estado"], reglas)
        _csv(carpeta / "reconciliacion.csv", ["carga_id", "destino", "tabla_staging", "leidas", "cargadas", "otra_toma",
                                              "sin_valor", "duplicado", "cuarentena"], self.detalle)
        _csv(carpeta / "completitud.csv", ["columna", "filas", "vacias", "porcentaje"], self.completitud())
        return carpeta


def _csv(ruta: Path, columnas: list[str], filas: list[dict]) -> None:
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)


def leer_bitacora(conexion: Connection, modelo: str) -> tuple[list[Carga], list[dict]]:
    """Las últimas cargas exitosas del modelo (una por fuente) y el balance por uso de cada una, solo conteos."""
    cargas = [Carga(*fila) for fila in conexion.execute(text(
        "SELECT DISTINCT ON (fuente) id, fuente, run_id_staging, ejecutado_en, filas_origen, filas_cargadas, "
        "filas_no_usadas, filas_cuarentena FROM etl_control.carga WHERE modelo = :modelo AND exitosa "
        "ORDER BY fuente, id DESC"
    ), {"modelo": modelo}).all()]
    detalle = [dict(fila) for fila in conexion.execute(text(
        "SELECT carga_id, destino, tabla_staging, leidas, cargadas, otra_toma, sin_valor, duplicado, cuarentena "
        "FROM etl_control.carga_detalle WHERE carga_id = ANY(:ids) ORDER BY carga_id, destino, tabla_staging"
    ), {"ids": [c.id for c in cargas]}).mappings().all()]
    return cargas, detalle


def construir_reporte(conexion: Connection, contrato: Contrato, ahora: datetime | None = None,
                      lector: str | None = None, reportes_dir: str | None = None,
                      staging_dirs: dict[str, str] | None = None,
                      permitidos: dict[str, dict[str, list[str]]] | None = None) -> Reporte:
    """
    Ejecuta todas las verificaciones sobre la bodega y reúne su resultado con la bitácora. `lector` (rol de Power BI) y
    `reportes_dir` (reportes de la transformación) habilitan QR-SEG-01 y QR-TRZ-01; `staging_dirs` ({fuente: carpeta}), QR-EXA-04;
    `permitidos` (listas de valores por atributo), QR-DOM-04.
    """
    cargas, detalle = leer_bitacora(conexion, contrato.modelo)
    return Reporte(modelo=contrato.modelo, generado_en=ahora or datetime.now(), cargas=cargas, detalle=detalle,
                   resultados=verificar_bodega(conexion, contrato, lector=lector, reportes_dir=reportes_dir,
                                              staging_dirs=staging_dirs, permitidos=permitidos))
