import pandas as pd
import pytest

from etl.transform.redcap.instrumentos.procedimientos import (
    COL_DURACION,
    COL_FIN,
    COL_INICIO,
    NOMBRE,
    resolver_fechas_procedimiento,
    transformar,
)

LLEGADA = "fecha_y_hora_de_llegada_del_paciente"
ALTA = "fecha_y_hora_de_alta"
CORRECCION_FIN = "fin anterior a inicio y fuera de la estancia por mas del margen"
CORRECCION_INICIO = "inicio posterior al fin y fuera de la estancia por mas del margen"


@pytest.fixture
def bloques():
    """
    Bloques de los que depende procedimientos (decisión 2.19), ya transformados: llegada de la demografía y alta
    de la hospitalización de dos episodios ficticios. Episodio 1: 10 al 15 de enero de 2024; episodio 2: 1 al 3 de
    febrero de 2024.
    """
    return {
        "informacion_demografica": pd.DataFrame({
            "record_id": ["1", "2"], LLEGADA: pd.to_datetime(["2024-01-10 08:30", "2024-02-01 20:00"])}),
        "hospitalizacion": pd.DataFrame({
            "record_id": ["1", "2"], ALTA: pd.to_datetime(["2024-01-15 12:00", "2024-02-03 10:00"])}),
    }


@pytest.fixture
def procedimientos():
    """
    Cuatro procedimientos ficticios (texto, como llega del export):
      1. coherente (1 h 30 min), episodio 1;
      2. fin anterior al inicio y fin fuera de la estancia (diciembre de 2023), inicio dentro, episodio 1;
      3. fin anterior al inicio con ambos dentro de la estancia (sin evidencia), episodio 2;
      4. fin anterior al inicio e inicio fuera de la estancia (marzo de 2024), fin dentro, episodio 2.
    """
    return pd.DataFrame({
        "record_id": ["1", "1", "2", "2"],
        COL_INICIO: ["2024-01-10 10:00", "2024-01-11 10:00", "2024-02-02 12:00", "2024-03-20 10:00"],
        COL_FIN: ["2024-01-10 11:30", "2023-12-01 11:00", "2024-02-02 08:00", "2024-02-02 09:00"],
    })


class TestInstrumentoProcedimientos:
    def test_resolucion_basada_en_evidencia(self, procedimientos, bloques, reporte):
        """
        Qué es: prueba unitaria de procedimientos.transformar (decisión 2.19, resolución con evidencia).
        Qué hace: transforma los cuatro procedimientos sintéticos con la llegada y el alta de sus episodios.
        Esperado: se invalida el fin del caso 2 y el inicio del caso 4 (la fecha que cae fuera por más del margen);
                  el caso 3 no tiene evidencia y conserva ambas fechas; cada corrección queda registrada con 1 fila.
        """
        # Arrange: fixtures

        # Act: transformar
        resultado = transformar(procedimientos, reporte, bloques)

        # Assert: solo las fechas con evidencia se invalidan
        assert pd.isna(resultado.loc[1, COL_FIN]) and pd.notna(resultado.loc[1, COL_INICIO])
        assert pd.isna(resultado.loc[3, COL_INICIO]) and pd.notna(resultado.loc[3, COL_FIN])
        assert pd.notna(resultado.loc[2, COL_INICIO]) and pd.notna(resultado.loc[2, COL_FIN])
        assert reporte.correcciones[(NOMBRE, COL_FIN, CORRECCION_FIN)]["filas_afectadas"] == 1
        assert reporte.correcciones[(NOMBRE, COL_INICIO, CORRECCION_INICIO)]["filas_afectadas"] == 1

    def test_reglas_cuentan_el_total_y_los_casos_sin_evidencia(self, procedimientos, bloques, reporte, regla):
        """
        Qué es: prueba unitaria de las reglas de procedimientos.
        Qué hace: transforma los cuatro procedimientos.
        Esperado: la regla original sigue contando el total antes de resolver (4 evaluables, 3 que incumplen) y la de
                  revisión manual cuenta solo el caso sin evidencia (3 evaluables, 1 que incumple).
        """
        # Arrange: fixtures

        # Act: transformar
        transformar(procedimientos, reporte, bloques)

        # Assert: total antes de resolver y casos para revisión manual
        assert regla(NOMBRE, "fecha_y_hora_de_fin_procedimiento anterior a fecha_y_hora_de_procedimiento") == (4, 3)
        assert regla(NOMBRE, "sin evidencia para corregir") == (3, 1)

    def test_duracion_en_segundos_con_na_donde_no_hay_dato_confiable(self, procedimientos, bloques, reporte):
        """
        Qué es: prueba unitaria de la duración derivada (NA cuando el fin es anterior al inicio).
        Qué hace: transforma los cuatro procedimientos y revisa duracion_procedimiento_seg.
        Esperado: 5400 s para el caso coherente; nulo para los casos con una fecha invalidada y para el negativo
                  sin evidencia (1 fuera de rango en la auditoría); tipo Int64 y sin pérdidas sin explicar.
        """
        # Arrange: fixtures

        # Act: transformar
        resultado = transformar(procedimientos, reporte, bloques)

        # Assert: duración solo donde es confiable
        assert str(resultado[COL_DURACION].dtype) == "Int64"
        assert resultado.loc[0, COL_DURACION] == 5400
        assert resultado[COL_DURACION].isna().tolist() == [False, True, True, True]
        assert reporte.auditoria[(NOMBRE, COL_DURACION)]["fuera_de_rango"] == 1
        reporte.verificar_auditoria()

    def test_duracion_de_mas_de_24_horas_solo_se_reporta(self, bloques, reporte, regla):
        """
        Qué es: prueba unitaria de la regla informativa de 24 h.
        Qué hace: transforma un procedimiento de 30 horas dentro de la estancia.
        Esperado: la duración se conserva (108000 s) y la regla informa 1 de 1 evaluable.
        """
        # Arrange: un procedimiento largo y coherente en el episodio 1
        df = pd.DataFrame({"record_id": ["1"], COL_INICIO: ["2024-01-11 00:00"], COL_FIN: ["2024-01-12 06:00"]})

        # Act: transformar
        resultado = transformar(df, reporte, bloques)

        # Assert: conservada y reportada
        assert resultado.loc[0, COL_DURACION] == 108000
        assert regla(NOMBRE, "superior a 24 h") == (1, 1)

    def test_sin_el_bloque_del_que_depende_falla(self, procedimientos, bloques, reporte):
        """
        Qué es: prueba unitaria de la dependencia entre instrumentos (bloques.DEPENDENCIAS).
        Qué hace: transforma sin el bloque de hospitalización, como si se hubiera procesado en el orden incorrecto.
        Esperado: KeyError que nombra el bloque faltante, en lugar de producir una resolución sin alta.
        """
        # Arrange: se quita la hospitalización
        del bloques["hospitalizacion"]

        # Act + Assert: se detiene
        with pytest.raises(KeyError, match="hospitalizacion"):
            transformar(procedimientos, reporte, bloques)


class TestResolverFechasProcedimiento:
    @pytest.fixture
    def referencia(self, bloques):
        """Una fila por episodio con la llegada y el alta (la tabla que construye procedimientos.transformar)."""
        return bloques["informacion_demografica"].merge(bloques["hospitalizacion"], on="record_id")

    @pytest.fixture
    def fechas(self, procedimientos):
        """Los procedimientos del fixture con las fechas ya convertidas a datetime."""
        procedimientos[COL_INICIO] = pd.to_datetime(procedimientos[COL_INICIO])
        procedimientos[COL_FIN] = pd.to_datetime(procedimientos[COL_FIN])
        return procedimientos

    def test_un_margen_muy_amplio_deja_todo_sin_evidencia(self, fechas, referencia, reporte, regla):
        """
        Qué es: prueba unitaria del parámetro margen_horas.
        Qué hace: resuelve los procedimientos con un margen de 100 000 horas (más de 11 años).
        Esperado: ninguna fecha se considera fuera de la estancia, no se invalida nada (0 filas en las dos
                  correcciones) y los 3 casos inconsistentes quedan para revisión manual.
        """
        # Arrange: fechas del fixture

        # Act: resolver con un margen enorme
        resolver_fechas_procedimiento(fechas, referencia, reporte, margen_horas=100_000)

        # Assert: sin correcciones y todo para revisión manual
        assert reporte.correcciones[(NOMBRE, COL_FIN, CORRECCION_FIN)]["filas_afectadas"] == 0
        assert reporte.correcciones[(NOMBRE, COL_INICIO, CORRECCION_INICIO)]["filas_afectadas"] == 0
        assert regla(NOMBRE, "sin evidencia para corregir") == (3, 3)
        assert fechas[[COL_INICIO, COL_FIN]].notna().all().all()

    def test_procedimiento_sin_episodio_de_referencia_queda_sin_evidencia(self, fechas, referencia, reporte, regla):
        """
        Qué es: prueba unitaria de un procedimiento cuyo episodio no está en la referencia.
        Qué hace: quita el episodio 2 de la referencia y resuelve.
        Esperado: los casos del episodio 2 no se corrigen (sin llegada ni alta no hay evidencia) y se cuentan para
                  revisión manual; los del episodio 1 se resuelven normalmente.
        """
        # Arrange: referencia sin el episodio 2
        referencia = referencia[referencia["record_id"] == "1"]

        # Act: resolver
        resolver_fechas_procedimiento(fechas, referencia, reporte)

        # Assert: solo se corrige el fin del episodio 1; los 2 del episodio 2 pasan a revisión manual
        assert reporte.correcciones[(NOMBRE, COL_FIN, CORRECCION_FIN)]["filas_afectadas"] == 1
        assert reporte.correcciones[(NOMBRE, COL_INICIO, CORRECCION_INICIO)]["filas_afectadas"] == 0
        assert regla(NOMBRE, "sin evidencia para corregir") == (3, 2)

    def test_referencia_con_episodio_repetido_falla(self, fechas, referencia, reporte):
        """
        Qué es: prueba unitaria de la validación de la referencia (many_to_one).
        Qué hace: duplica un episodio en la referencia.
        Esperado: MergeError: una llegada o alta ambigua no puede decidir qué fecha es la errónea.
        """
        # Arrange: episodio 1 repetido
        referencia = pd.concat([referencia, referencia.iloc[[0]]], ignore_index=True)

        # Act + Assert: se detiene
        with pytest.raises(pd.errors.MergeError):
            resolver_fechas_procedimiento(fechas, referencia, reporte)
