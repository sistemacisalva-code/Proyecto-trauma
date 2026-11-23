"""
TC-CAL-10 (unitaria): las columnas reservadas de etl/quality/bodega.py frente a la lista de exclusión de los permisos.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Solo lee el script de permisos versionado: no usa base de datos ni datos de pacientes.
"""
from pathlib import Path
import re

from etl.quality.bodega import COLUMNAS_RESERVADAS

PERMISOS = Path(__file__).resolve().parents[2] / "database" / "schema" / "04_permissions.sql"


class TestColumnasReservadas:
    def test_coinciden_con_la_exclusion_de_04_permissions(self):
        """
        Qué es: prueba unitaria de sincronía entre QR-SEG-01 y el script de permisos del rol lector.
        Qué hace: extrae de 04_permissions.sql la lista `excluidas` del modelo completo y la compara con
                  COLUMNAS_RESERVADAS.
        Esperado: el mismo conjunto de (tabla, columna): si se excluye o incluye una columna en un lado y no en el
                  otro, la verificación de seguridad dejaría de reflejar lo que concede el script.
        """
        # Arrange: bloque de la lista de exclusión del script
        sql = PERMISOS.read_text(encoding="utf-8")
        bloque = sql.split("excluidas TEXT[] := ARRAY[")[1].split("];")[0]

        # Act
        excluidas = set(re.findall(r"'trauma_completo\.(\w+)\.(\w+)'", bloque))

        # Assert
        assert excluidas == set(COLUMNAS_RESERVADAS)
