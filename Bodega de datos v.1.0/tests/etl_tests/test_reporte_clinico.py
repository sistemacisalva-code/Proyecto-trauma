"""
Pruebas del reporte para quien corrige (`etl/transform/common/reporte_clinico.py`) y de su escritura en disco.

Todo es sintético: reportes armados en memoria con llaves, campos y reglas inventados (sin datos clínicos). Las pruebas
comprueban que el documento dice dónde mirar y por qué (llave, instrumento, campos, motivo) y que nunca contiene valores.
"""
import os

import pandas as pd

from etl.load.staging_writer import save_transform_result
from etl.transform.base import TransformResult
from etl.transform.common.reporte_clinico import COLUMNAS_CSV, construir_para_correccion, tabla_para_correccion

VALOR_SECRETO = "VALOR-CLINICO-SECRETO"


def _reporte_con_casos(reporte):
    """
    Completa el `reporte` del fixture con tres casos sintéticos: una regla que se conserva (registro 2 y 10 de
    hospitalización), una corrección de un procedimiento del registro 10 y un valor fuera de rango del registro 2. Las
    llaves están en el orden 10, 2 para comprobar el orden natural. El valor secreto está solo en una tabla de la que el
    reporte no guarda valores (se usa para comprobar que no llega al documento).
    """
    llaves = pd.Series(["10", "2"], index=[0, 1])
    marcas = pd.Series([True, True], index=[0, 1])
    reporte.reportar_regla("hospitalizacion", "fecha_y_hora_de_alta anterior a fecha_de_admision", marcas, marcas, llaves,
                           ["fecha_de_admision", "fecha_y_hora_de_alta"])
    reporte.registrar_correccion("procedimientos", "fecha_y_hora_de_fin_procedimiento",
                                 "fin anterior a inicio y fuera de la estancia", 1, "invalidado (NA)", llaves,
                                 pd.Series([True, False], index=[0, 1]),
                                 ["fecha_y_hora_de_fin_procedimiento", "fecha_y_hora_de_procedimiento"])
    reporte.detallar("signos_vitales", "frecuencia_cardiaca fuera de rango (invalidado)", "invalidada",
                     "frecuencia_cardiaca", llaves, pd.Series([False, True], index=[0, 1]), ["frecuencia_cardiaca"])
    reporte.registrar_auditoria("signos_vitales", "fc", pd.Series([VALOR_SECRETO]), pd.Series([pd.NA], dtype="string"),
                                no_convertibles=1)
    return reporte


class TestReporteParaCorreccion:
    def test_agrupa_por_registro_con_instrumento_campos_y_motivo(self, reporte):
        """
        Qué es: prueba unitaria de `construir_para_correccion` (reporte para el personal médico).
        Qué hace: arma el reporte de una corrida sintética de REDCap con una regla, una corrección y una invalidación.
        Esperado: el Markdown abre con el aviso de confidencialidad, trae un bloque por registro en orden natural (2 antes
                  que 10), con instrumento, campos, motivo y qué se hizo con el dato.
        """
        # Arrange
        _reporte_con_casos(reporte)

        # Act
        md, tabla = construir_para_correccion(reporte, "redcap", "2026-10-31T120000")

        # Assert
        assert "**CONFIDENCIAL.**" in md and "`record_id`" in md and "RC-<record_id>" in md
        assert md.index("### Registro 2") < md.index("### Registro 10")
        assert ("| hospitalizacion | fecha_de_admision; fecha_y_hora_de_alta | fecha_y_hora_de_alta anterior a "
                "fecha_de_admision | Se conservó el dato; revisar y corregir en la fuente si es un error | 1 |") in md
        assert "Se dejó vacío «fecha_y_hora_de_fin_procedimiento» en el staging" in md
        assert "estaba fuera del dominio válido y se dejó vacío" in md
        assert "**Resumen:** 2 registros con al menos un caso" in md

    def test_la_tabla_para_el_csv_trae_las_columnas_y_el_avance_vacio(self, reporte):
        """
        Qué es: prueba unitaria de `tabla_para_correccion` (lo que se escribe en el CSV).
        Qué hace: arma la tabla de la corrida sintética.
        Esperado: tiene exactamente las columnas del CSV, una fila por registro y regla (4), ordenadas por registro, con la
                  columna `corregido` vacía para que el médico anote el avance; el instrumento sale del prefijo del campo o
                  del bloque.
        """
        # Arrange
        _reporte_con_casos(reporte)

        # Act
        tabla = tabla_para_correccion(reporte)

        # Assert
        assert list(tabla.columns) == COLUMNAS_CSV and len(tabla) == 4
        assert tabla["llave"].tolist() == ["2", "2", "10", "10"]
        assert set(tabla["corregido"]) == {""}
        assert set(tabla["instrumento"]) == {"hospitalizacion", "procedimientos", "signos_vitales"}

    def test_no_incluye_valores_del_reporte(self, reporte):
        """
        Qué es: prueba unitaria de privacidad del reporte para quien corrige.
        Qué hace: arma el reporte con un valor reconocible en la auditoría (que guarda conteos, no valores) y revisa el
                  documento y la tabla.
        Esperado: el valor no aparece en el Markdown ni en la tabla: el documento trae llaves, no valores.
        """
        # Arrange
        _reporte_con_casos(reporte)

        # Act
        md, tabla = construir_para_correccion(reporte, "excel", "2026-10-31T120000")

        # Assert
        assert VALOR_SECRETO not in md and VALOR_SECRETO not in tabla.to_csv()
        assert "`traumaregisterrecordid`" in md and "EX-<id>" in md

    def test_sin_casos_dice_que_no_hay_registros_marcados(self, reporte):
        """
        Qué es: prueba unitaria del reporte para quien corrige sin hallazgos.
        Qué hace: construye el reporte de una corrida sin detalle de filas.
        Esperado: el Markdown lo indica, y la tabla está vacía pero con sus columnas.
        """
        # Arrange: reporte vacío del fixture

        # Act
        md, tabla = construir_para_correccion(reporte, "redcap", "2026-10-31T120000")

        # Assert
        assert "No hay registros marcados en esta corrida." in md
        assert tabla.empty and list(tabla.columns) == COLUMNAS_CSV


class TestEscrituraParaCorreccion:
    def _resultado(self, reporte) -> TransformResult:
        tablas = {"informacion_demografica": pd.DataFrame({"trauma_register_id": ["RC-1"], "valor": [1]})}
        return TransformResult(tables=tablas, reporte=reporte, source_type="redcap", rows={"informacion_demografica": 1},
                               elapsed_seconds=1.0, transformed_at="2026-10-31T12:00:00+00:00")

    def test_escribe_el_md_y_el_csv_solo_si_hay_casos(self, reporte, tmp_path):
        """
        Qué es: prueba unitaria de la escritura de `para_correccion.md` y `para_correccion.csv`.
        Qué hace: guarda una corrida sin casos y otra con casos, cada una en su carpeta temporal.
        Esperado: sin casos no se escriben; con casos aparecen en la carpeta del reporte y el CSV se lee con separador
                  `;` con las columnas esperadas.
        """
        # Arrange: una corrida vacía y otra con casos
        vacia = self._resultado(type(reporte)())
        con_casos = self._resultado(_reporte_con_casos(reporte))

        # Act
        rutas_vacia = save_transform_result(vacia, staging_dir=str(tmp_path / "a" / "s"), reports_dir=str(tmp_path / "a" / "r"))
        rutas_casos = save_transform_result(con_casos, staging_dir=str(tmp_path / "b" / "s"), reports_dir=str(tmp_path / "b" / "r"))

        # Assert
        assert not os.path.exists(os.path.join(rutas_vacia["reporte"], "para_correccion.md"))
        assert not os.path.exists(os.path.join(rutas_vacia["reporte"], "para_correccion.csv"))
        assert os.path.exists(os.path.join(rutas_casos["reporte"], "para_correccion.md"))
        csv = pd.read_csv(os.path.join(rutas_casos["reporte"], "para_correccion.csv"), sep=";", dtype=str)
        assert list(csv.columns) == COLUMNAS_CSV and len(csv) == 4
