"""Seudonimización de identificadores directos (Habeas Data)."""
import hashlib
import hmac

import pandas as pd

LONGITUD_MINIMA_CLAVE = 16  # bytes


def seudonimizar(serie: pd.Series, clave: str | bytes) -> pd.Series:
    """HMAC-SHA256 (hexadecimal) del identificador normalizado; nulo si no hay identificador.

    Se normaliza antes de aplicar el HMAC (mayúsculas y solo letras y dígitos) para que '1.234' y
    '1234' den el mismo resultado. El mismo documento produce siempre el mismo digest mientras la
    clave no cambie, por lo que sirve para detectar pacientes repetidos sin exponer el documento.
    Un hash simple no basta: el espacio de números de documento es pequeño y se recupera por fuerza bruta.

    Raises:
        ValueError: si la clave está vacía o es demasiado corta.
    """
    clave = clave.encode("utf-8") if isinstance(clave, str) else clave
    if not clave or len(clave) < LONGITUD_MINIMA_CLAVE:
        raise ValueError(f"La clave de seudonimización debe tener al menos {LONGITUD_MINIMA_CLAVE} bytes; "
                         "definir PSEUDONYMIZATION_KEY en el .env")

    base = serie.astype("string").str.upper().str.replace(r"[^0-9A-Z]", "", regex=True)
    base = base.mask(base == "")  # un identificador sin caracteres válidos es ausencia de dato

    def _hmac(valor: str) -> str:
        return hmac.new(clave, valor.encode("utf-8"), hashlib.sha256).hexdigest()

    return base.map(_hmac, na_action="ignore").astype("string")
