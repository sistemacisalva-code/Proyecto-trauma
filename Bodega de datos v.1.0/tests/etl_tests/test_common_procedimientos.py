import pandas as pd
import pytest

from etl.transform.common.procedimientos import (
    COL_ALTA,
    COL_DURACION,
    COL_FIN,
    COL_INICIO,
    COL_LLEGADA,
    reportar_duracion_cero,
    reportar_duracion_extensa,
    resolver_fechas_procedimiento,
)

LLAVE_EXCEL = "traumaregisterrecordid"
BLOQUE_EXCEL = "procedimientos_excel"


@pytest.fixture
def estancia():
    """
    Estancia sintética de un episodio del Excel (llegada 01/03 08:00, alta 05/03 08:00), con la llave del Excel.
    Datos inventados: sin ningún registro real.
    """
    return pd.DataFrame({LLAVE_EXCEL: ["E1"],
                         COL_LLEGADA: pd.to_datetime(["2015-03-01 08:00"]),
                         COL_ALTA: pd.to_datetime(["2015-03-05 08:00"])})


@pytest.fixture
def procedimientos_excel():
    """
    Tres procedimientos sintéticos del episodio E1 con la llave del Excel: el fin cae un año antes (fuera de la
    estancia, antes del inicio), el inicio cae un año después del alta (posterior al fin), y uno coherente.
    Aislados del instrumento de REDCap.
    """
    return pd.DataFrame({
        LLAVE_EXCEL: ["E1", "E1", "E1"],
        COL_INICIO: pd.to_datetime(["2015-03-02 10:00", "2016-03-02 10:00", "2015-03-02 10:00"]),
        COL_FIN: pd.to_datetime(["2014-03-02 11:00", "2015-03-02 09:00", "2015-03-02 11:00"]),
    })


class TestResolverFechasProcedimientoComun:
    def test_resuelve_con_la_llave_y_el_bloque_de_otra_fuente(self, procedimientos_excel, estancia, reporte):
        """
        Qué es: prueba unitaria de la regla compartida (common/procedimientos.py) con parámetros de fuente.
        Qué hace: resuelve procedimientos que usan la llave del Excel (traumaregisterrecordid) y otro nombre de
                  bloque, sin pasar por el instrumento de REDCap.
        Esperado: se invalida el fin fuera de la estancia (fila 0) y el inicio fuera de la estancia (fila 1), la
                  fila coherente no cambia y las correcciones quedan registradas en el bloque indicado.
        """
        # Arrange: fixtures con la llave del Excel

        # Act: resolver con la llave y el bloque propios
        resolver_fechas_procedimiento(procedimientos_excel, estancia, reporte, BLOQUE_EXCEL, llave=LLAVE_EXCEL)

        # Assert: cada fecha errónea invalidada, la coherente intacta, conteos en el bloque del Excel
        assert pd.isna(procedimientos_excel.loc[0, COL_FIN])
        assert pd.isna(procedimientos_excel.loc[1, COL_INICIO])
        assert procedimientos_excel.loc[2, [COL_INICIO, COL_FIN]].notna().all()
        filas = {(b, c): v["filas_afectadas"] for (b, c, _), v in reporte.correcciones.items()}
        assert filas == {(BLOQUE_EXCEL, COL_FIN): 1, (BLOQUE_EXCEL, COL_INICIO): 1}

    def test_sin_margen_una_fecha_fuera_por_una_hora_se_invalida(self, estancia, reporte):
        """
        Qué es: prueba unitaria del margen por defecto de la estancia en la resolución de procedimientos (0 h desde el
                2026-10-31, por indicación del personal médico; antes eran 7 días).
        Qué hace: resuelve dos procedimientos sintéticos con el fin anterior al inicio: en el primero el fin cae una hora
                  antes de la llegada; en el segundo, justo en la llegada.
        Esperado: se invalida el fin del primero (fuera de la estancia por una hora, con el inicio dentro) y se conserva
                  el del segundo (el extremo cuenta como dentro, así que ambas fechas están dentro y no hay evidencia).
        """
        # Arrange: estancia del 01/03 08:00 al 05/03 08:00; los dos inicios están dentro
        procedimientos = pd.DataFrame({
            LLAVE_EXCEL: ["E1", "E1"],
            COL_INICIO: pd.to_datetime(["2015-03-02 10:00", "2015-03-02 10:00"]),
            COL_FIN: pd.to_datetime(["2015-03-01 07:00", "2015-03-01 08:00"]),
        })

        # Act: sin margen explícito (usa el valor por defecto)
        resolver_fechas_procedimiento(procedimientos, estancia, reporte, BLOQUE_EXCEL, llave=LLAVE_EXCEL)

        # Assert: solo el fin que excede el extremo se invalida
        assert pd.isna(procedimientos.loc[0, COL_FIN])
        assert procedimientos.loc[1, COL_FIN] == pd.Timestamp("2015-03-01 08:00")
        assert {(b, c): v["filas_afectadas"] for (b, c, _), v in reporte.correcciones.items()
                }[(BLOQUE_EXCEL, COL_FIN)] == 1

    def test_duracion_extensa_se_reporta_en_el_bloque_indicado(self, reporte, regla):
        """
        Qué es: prueba unitaria de la regla compartida de duración superior a 24 h.
        Qué hace: evalúa tres duraciones (1 h, 25 h y vacía) en un bloque con nombre propio.
        Esperado: 2 evaluables y 1 que supera las 24 h, registrada en ese bloque; no modifica los datos.
        """
        # Arrange: duraciones en segundos
        df = pd.DataFrame({COL_DURACION: pd.array([3600, 25 * 3600, None], dtype="Int64")})

        # Act: reportar
        reportar_duracion_extensa(df, reporte, BLOQUE_EXCEL)

        # Assert: conteo correcto y datos sin cambios
        assert regla(BLOQUE_EXCEL, "superior a 24 h") == (2, 1)
        assert df[COL_DURACION].notna().sum() == 2


class TestDuracionCeroComun:
    def test_duracion_cero_se_reporta_sin_modificar_datos(self, reporte, regla):
        """
        Qué es: prueba unitaria de la regla compartida de duración de 0 segundos (common/procedimientos.py).
        Qué hace: evalúa cuatro duraciones sintéticas (0 s, 60 s, 0 s y vacía) en un bloque con nombre propio.
        Esperado: 3 evaluables y 2 en cero, registradas en ese bloque; la columna queda intacta (solo se reporta).
        """
        # Arrange: duraciones en segundos, con dos ceros y un vacío (el vacío no es evaluable)
        df = pd.DataFrame({COL_DURACION: pd.array([0, 60, 0, None], dtype="Int64")})
        antes = df.copy()

        # Act: reportar
        reportar_duracion_cero(df, reporte, BLOQUE_EXCEL)

        # Assert: conteo correcto y datos sin cambios (el cero no se invalida: puede ser un procedimiento instantáneo)
        assert regla(BLOQUE_EXCEL, "igual a 0 s") == (3, 2)
        pd.testing.assert_frame_equal(df, antes)


class TestDetalleDeFilasDeProcedimientos:
    def test_la_correccion_y_el_caso_sin_evidencia_dejan_su_llave(self, estancia, reporte):
        """
        Qué es: prueba unitaria del detalle de filas de `resolver_fechas_procedimiento` (para corregir en la fuente).
        Qué hace: resuelve dos episodios sintéticos con el fin anterior al inicio: E1 con el fin fuera de la estancia
                  (se invalida) y E2 con ambas fechas dentro (sin evidencia).
        Esperado: detalle_filas guarda E1 como "corregida" en la columna del fin y E2 como "incumple" de la regla de
                  revisión manual; ninguna otra llave.
        """
        # Arrange: dos episodios con la misma estancia (01/03 08:00 a 05/03 08:00)
        ref = pd.concat([estancia, estancia.assign(**{LLAVE_EXCEL: "E2"})], ignore_index=True)
        procedimientos = pd.DataFrame({
            LLAVE_EXCEL: ["E1", "E2"],
            COL_INICIO: pd.to_datetime(["2015-03-02 10:00", "2015-03-03 10:00"]),
            COL_FIN: pd.to_datetime(["2014-03-02 11:00", "2015-03-02 09:00"]),
        })

        # Act
        resolver_fechas_procedimiento(procedimientos, ref, reporte, BLOQUE_EXCEL, llave=LLAVE_EXCEL)

        # Assert
        detalle = reporte.tabla("detalle_filas")
        corregida = detalle[detalle["tipo"] == "corregida"]
        revision = detalle[detalle["tipo"] == "incumple"]
        assert corregida[["llave", "columna"]].values.tolist() == [["E1", COL_FIN]]
        assert revision["llave"].tolist() == ["E2"]
