"""
TC-CAL-27 y TC-CAL-28: ida y vuelta de los puentes contra el staging (QR-EXA-05, etl/quality/puentes.py) sobre la bodega
cargada con el staging sintético.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Las carpetas del staging son las mismas que cargó el fixture del módulo (sintéticas, sin datos reales); los defectos se
inyectan en los puentes dentro de la transacción de la prueba, que se revierte al terminar.
"""
from sqlalchemy import text

from etl.quality.puentes import verificar_puentes_contra_staging
from tests.quality_tests.ayudas import por_regla

ESQUEMA = "trauma_completo"
DIAGNOSTICO = "x.rol = 'diagnostico'"
DIAGNOSTICO_SIN_CODIGO = "x.rol = 'diagnostico' AND x.texto_origen IS NOT NULL"


def _primera_atencion(puente: str, fuente: str, condicion: str = "TRUE") -> str:
    """Subconsulta con el hecho de la primera atención de la fuente que tiene filas en el puente."""
    return (f"(SELECT min(x.fact_id) FROM {ESQUEMA}.{puente} x JOIN {ESQUEMA}.fact_trauma h USING (fact_id) "
            f"WHERE h.trauma_register_id LIKE '{fuente}-%' AND {condicion})")


class TestIdaYVueltaDePuentes:
    def test_tc_cal_27_los_puentes_coinciden_con_el_staging(self, conexion, contrato, staging_dirs):
        """
        Que es: prueba de calidad de la regla QR-EXA-05 (ida y vuelta de los puentes), caso que cumple.
        Que hace: compara, por puente, rol y fuente, el conjunto de filas de cada atención con el del staging cargado.
        Esperado: una verificación por puente (y rol) y fuente que tiene filas en el staging, con atenciones evaluadas
                  y ninguna distinta.
        """
        # Arrange: bodega y staging cargados por los fixtures del módulo
        esperadas = sum(1 for _, tipo, bloque in contrato.bloques() if tipo == "puente"
                        for fuente in ("excel", "redcap") if bloque["filas"][fuente] is not None)

        # Act
        resultados = verificar_puentes_contra_staging(conexion, contrato, staging_dirs)

        # Assert
        assert len(resultados) == esperadas
        assert all(r.regla == "QR-EXA-05" and r.evaluadas > 0 and r.cumple for r in resultados)

    def test_tc_cal_28_detecta_una_imagen_cambiada_un_codigo_borrado_y_un_texto_alterado(
            self, conexion, contrato, staging_dirs):
        """
        Que es: prueba de calidad de la regla QR-EXA-05, casos defectuosos (la carga se equivocó al armar un puente).
        Que hace: cambia el tipo de imagen de una atención del Excel, borra el diagnóstico de una de REDCap y altera el
                  texto sin código de un diagnóstico del Excel.
        Esperado: exactamente tres verificaciones incumplen, cada una con 1 atención: imágenes del Excel, diagnóstico de
                  REDCap y diagnóstico del Excel.
        """
        # Arrange
        conexion.execute(text(
            f"UPDATE {ESQUEMA}.bridge_atencion_imagen b SET imagen_id = (SELECT i.imagen_id FROM {ESQUEMA}.dim_imagen i "
            "WHERE i.imagen_id <> b.imagen_id ORDER BY i.imagen_id LIMIT 1) "
            f"WHERE b.fact_id = {_primera_atencion('bridge_atencion_imagen', 'EX')}"))
        conexion.execute(text(
            f"DELETE FROM {ESQUEMA}.bridge_atencion_cie_10 WHERE rol = 'diagnostico' AND fact_id = "
            f"{_primera_atencion('bridge_atencion_cie_10', 'RC', DIAGNOSTICO)}"))
        conexion.execute(text(
            f"UPDATE {ESQUEMA}.bridge_atencion_cie_10 SET texto_origen = texto_origen || ' alterado' WHERE rol = 'diagnostico' AND "
            f"texto_origen IS NOT NULL AND fact_id = "
            f"{_primera_atencion('bridge_atencion_cie_10', 'EX', DIAGNOSTICO_SIN_CODIGO)}"))

        # Act
        resultados = verificar_puentes_contra_staging(conexion, contrato, staging_dirs)

        # Assert
        distintos = sorted((r.detalle.split(":")[0], r.incumplen) for r in resultados if r.incumplen)
        assert distintos == [("bridge_atencion_cie_10[diagnostico] (excel)", 1),
                             ("bridge_atencion_cie_10[diagnostico] (redcap)", 1),
                             ("bridge_atencion_imagen (excel)", 1)]
