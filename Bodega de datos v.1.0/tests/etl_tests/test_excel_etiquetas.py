"""
Pruebas de las etiquetas del Excel que se alinean con las de REDCap: los mapeos nuevos del 2026-10-31, salidos de
comparar los valores de las dos fuentes atributo por atributo (diccionario de QR-DOM-04).

Todo es sintético: bloques de una columna armados en memoria con las etiquetas que cada fuente escribe, más un valor
inventado que ningún mapeo toca. No hay datos de pacientes ni lectura de archivos: solo se comprueba que el Excel quede
escrito como REDCap, que lo demás se conserve y que cada cambio quede contado en el reporte.
"""
import pandas as pd
import pytest

from etl.transform.excel.hojas import MAPEO_PARTE_IMAGENES, MAPEO_PERDIDA_CONCIENCIA
from etl.transform.excel.preparacion import estandarizar_etiquetas
from etl.transform.excel.registro import (
    MAPEO_CAIDA, MAPEO_ESTADO_CIVIL, MAPEO_MUERTE_PREVENIBLE, MAPEO_PACIENTE_ASEGURADO, MAPEO_VEHICULO)

BLOQUE = "bloque_sintetico"
AJENO = "VALOR-SINTETICO-AJENO"      # no está en ningún mapeo: debe conservarse tal cual
# Etiqueta del Excel -> etiqueta de REDCap, por columna, con el mapeo que las unifica
CASOS = [
    ("lesiones_de_caidas", MAPEO_CAIDA, {"No": "NO", "Si": "SI", "No especificado": "NO ESPECIFICADO"}),
    ("tipo_de_vehiculo", MAPEO_VEHICULO, {"Camión o trailer": "Camión o tráiler",
                                          "Vehículos todo terreno (Cuadrón)": "Vehículos todo terreno"}),
    ("estado_civil", MAPEO_ESTADO_CIVIL, {"Viudo": "Viudo/a", "Union Libre": "Unión libre"}),
    ("muerte_prevenible", MAPEO_MUERTE_PREVENIBLE, {"Si": "Sí"}),
    ("paciente_asegurado", MAPEO_PACIENTE_ASEGURADO, {"Si": "Sí"}),
    ("perdida_de_conciencia", MAPEO_PERDIDA_CONCIENCIA, {"No especificado": "Sin especificar"}),
    ("parte_del_cuerpo_imagenes", MAPEO_PARTE_IMAGENES,
     {"Tobillo Y Pie No Especificado": "Tobillo y Pie No Especificado"}),
]


class TestEtiquetasExcelAlineadasConRedcap:
    @pytest.mark.parametrize("columna,mapeo,esperado", CASOS, ids=[c[0] for c in CASOS])
    def test_la_etiqueta_del_excel_queda_como_la_de_redcap(self, columna, mapeo, esperado, reporte):
        """
        Qué es: prueba unitaria de cada mapeo de etiquetas del Excel hacia el dominio de REDCap.
        Qué hace: estandariza un bloque sintético con las etiquetas que escribe el Excel y un valor ajeno al mapeo.
        Esperado: cada etiqueta del Excel queda escrita como la de REDCap, el valor ajeno y los vacíos se conservan, y
                  el reporte cuenta exactamente las filas que cambiaron (el valor ajeno y el vacío no cuentan).
        """
        # Arrange: una fila por etiqueta del Excel, más el valor ajeno y un vacío
        df = pd.DataFrame({columna: [*esperado, AJENO, None]})

        # Act
        cambiadas = estandarizar_etiquetas(df, reporte, BLOQUE, columna, mapeo)

        # Assert: dominio unificado, resto intacto y cambio contado
        assert df[columna].tolist()[:len(esperado)] == list(esperado.values())
        assert df[columna].iloc[-2] == AJENO and pd.isna(df[columna].iloc[-1])
        assert cambiadas == len(esperado)

    @pytest.mark.parametrize("columna,mapeo,esperado", CASOS, ids=[c[0] for c in CASOS])
    def test_la_etiqueta_de_redcap_no_se_vuelve_a_cambiar(self, columna, mapeo, esperado, reporte):
        """
        Qué es: prueba unitaria de idempotencia de los mapeos (ningún destino es origen de otra regla).
        Qué hace: estandariza un bloque que ya trae las etiquetas de REDCap.
        Esperado: nada cambia y el reporte cuenta 0 filas: aplicar el mapeo dos veces da el mismo resultado.
        """
        # Arrange: el bloque ya estandarizado
        df = pd.DataFrame({columna: list(esperado.values())})

        # Act
        cambiadas = estandarizar_etiquetas(df, reporte, BLOQUE, columna, mapeo)

        # Assert
        assert df[columna].tolist() == list(esperado.values()) and cambiadas == 0
