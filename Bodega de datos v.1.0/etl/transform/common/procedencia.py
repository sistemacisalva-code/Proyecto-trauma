"""Procedencia de una corrida de transformación: qué entrada se leyó y con qué versión del código y de la configuración.

Va al manifiesto del reporte de calidad para que cada corrida sea reproducible: misma partición de raw + mismo commit +
mismas huellas de configuración = misma salida. Solo nombres, conteos y huellas (sin datos).
"""
import hashlib
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
CATALOGOS = RAIZ / "config" / "catalogos"
CONFIG_COMUN = ("config/estandar_municipios.yaml",)   # reglas de common que leen config fuera de catalogos/


def huella_archivo(ruta: str | Path) -> str | None:
    """SHA-256 del contenido del archivo; None si no existe."""
    ruta = Path(ruta) if Path(ruta).is_absolute() else RAIZ / ruta
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def huellas_configuracion(rutas=()) -> dict[str, str | None]:
    """Huella de cada archivo de configuración: los propios del transformer, los catálogos y la config común."""
    archivos = [*rutas, *CONFIG_COMUN, *(str(p.relative_to(RAIZ)) for p in sorted(CATALOGOS.glob("*")) if p.is_file())]
    return {str(Path(r).as_posix()): huella_archivo(r) for r in dict.fromkeys(archivos)}


def version_codigo() -> dict:
    """Commit de git y si había cambios sin commit (en ese caso el commit no basta para reproducir la corrida).
    Si git no está disponible, devuelve los dos campos en None en lugar de fallar."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=10, check=True).stdout
    try:
        return {"commit": git("rev-parse", "HEAD").strip(), "cambios_sin_commit": bool(git("status", "--porcelain").strip())}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "cambios_sin_commit": None}
