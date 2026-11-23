"""
Verifica la calidad de la bodega ya cargada y escribe el reporte (solo conteos):

    python -m etl.quality --modelo completo

Usa las credenciales de la aplicación del entorno activo (APP_ENV, "development" por defecto), igual que la carga. Termina
con código 2 (`CODIGO_RECHAZADA`, el mismo de `--mode=all`) si el veredicto es Rechazada. La lógica vive en `etl.pipeline.run_quality`, la misma que usa el ETL completo.
"""
import argparse
import logging

from etl.load.warehouse.factory import MODELOS
from etl.pipeline import CODIGO_RECHAZADA, run_quality


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="etl.quality", description="Calidad de la bodega cargada.")
    parser.add_argument("--modelo", choices=list(MODELOS), required=True)
    args = parser.parse_args(argv)
    return CODIGO_RECHAZADA if run_quality(args.modelo) == "Rechazada" else 0


if __name__ == "__main__":
    raise SystemExit(main())
