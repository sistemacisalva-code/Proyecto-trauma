"""
TC-CAL-15 a TC-CAL-20, TC-CAL-26 y TC-CAL-35: verificaciones de los valores de la bodega (etl/quality/valores.py y dominios.py) sobre la bodega
cargada con el staging sintético: completitud (QR-NUL-01 a 04), validez (QR-DOM-01 a 04), consistencia (QR-CON-01 a 06) y tiempo
completo (QR-TIE-01).

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
El staging sintético respeta los rangos de la transformación y el orden de las fechas, y trae una atención vacía de
atributos (con su fecha de llegada) por fuente; los defectos se inyectan en la transacción de la prueba, que se revierte.
"""
from datetime import date

from sqlalchemy import text

from etl.quality.dominios import verificar_valores_permitidos
from etl.quality.valores import (
    verificar_atenciones_sin_puente, verificar_campos_criticos, verificar_cie10_sin_codigo, verificar_completitud, verificar_consistencia,
    verificar_rangos, verificar_tiempo_completo,
)
from tests.quality_tests.ayudas import por_regla

PRIMERA_ATENCION = "(SELECT min(trauma_register_id) FROM trauma_completo.fact_trauma)"
HOY = date(2026, 10, 27)   # el día de la carga del fixture: lo posterior es futuro


def _una_con(columna: str) -> str:
    """La primera atención que tiene la columna con valor."""
    return (f"(SELECT min(trauma_register_id) FROM trauma_completo.fact_trauma WHERE {columna} IS NOT NULL)")


class TestCompletitud:
    def test_tc_cal_15_campos_criticos_cumplen_y_detecta_una_fecha_vacia(self, conexion, contrato):
        """
        Que es: prueba de calidad de las reglas QR-NUL-01 (llave) y QR-NUL-04 (fecha de admisión) sin vacíos.
        Que hace: verifica la llave y la fecha de admisión de todas las atenciones; luego deja vacía la fecha de una.
        Esperado: al inicio 0 incumplimientos en las dos columnas; después, 1 en la fecha de admisión y 0 en la llave.
        """
        # Arrange: bodega cargada por el fixture del módulo
        inicial = verificar_campos_criticos(conexion, contrato)
        conexion.execute(text("UPDATE trauma_completo.fact_trauma SET fecha_admision_id = NULL "
                              f"WHERE trauma_register_id = {PRIMERA_ATENCION}"))

        # Act
        final = verificar_campos_criticos(conexion, contrato)

        # Assert
        assert all(r.evaluadas > 0 and r.cumple for r in inicial)
        (fecha,) = por_regla(final, "QR-NUL-04", "fecha_admision_id")
        (llave,) = por_regla(final, "QR-NUL-01", "trauma_register_id")
        assert (fecha.incumplen, llave.incumplen) == (1, 0)

    def test_tc_cal_16_cuenta_los_vacios_de_cada_columna(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-NUL-02 (vacíos por columna, informativa).
        Que hace: cuenta los vacíos de una medida y de un atributo de dimensión en la bodega sintética, que trae una
                  atención vacía de atributos por fuente.
        Esperado: la medida (peso) y el atributo (género de dim_paciente) tienen 2 vacíos sobre todas las atenciones: la
                  vacía de cada fuente (NULL en la medida, 'Sin dato' en el atributo); y hay una verificación para la
                  clave de cada dimensión sin contarla como columna.
        """
        # Arrange: bodega cargada por el fixture del módulo
        total = conexion.execute(text("SELECT count(*) FROM trauma_completo.fact_trauma")).scalar()

        # Act
        resultados = verificar_completitud(conexion, contrato)

        # Assert
        (peso,) = por_regla(resultados, "QR-NUL-02", "fact_trauma.peso")
        (genero,) = por_regla(resultados, "QR-NUL-02", "dim_paciente.genero")
        assert (peso.evaluadas, peso.incumplen) == (total, 2)
        assert (genero.evaluadas, genero.incumplen) == (total, 2)
        assert not por_regla(resultados, "QR-NUL-02", "fact_trauma.paciente_id")


class TestAtencionesSinPuente:
    def test_tc_cal_26_cuenta_las_atenciones_sin_filas_y_el_total(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-NUL-03 (atenciones sin filas en cada puente, informativa).
        Que hace: cuenta, por puente, rol y fuente, las atenciones sin filas y el total; luego borra las filas de
                  imágenes de una atención del Excel.
        Esperado: hay una verificación por fuente y una de total por puente y rol; el total es la suma de las fuentes;
                  tras borrar, las imágenes del Excel y el total suben en 1 y las de REDCap no cambian.
        """
        # Arrange
        inicial = verificar_atenciones_sin_puente(conexion, contrato)
        conexion.execute(text(
            "DELETE FROM trauma_completo.bridge_atencion_imagen WHERE fact_id = (SELECT min(b.fact_id) "
            "FROM trauma_completo.bridge_atencion_imagen b JOIN trauma_completo.fact_trauma h USING (fact_id) "
            "WHERE h.trauma_register_id LIKE 'EX-%')"))

        # Act
        final = verificar_atenciones_sin_puente(conexion, contrato)

        # Assert
        (excel0,) = por_regla(inicial, "QR-NUL-03", "bridge_atencion_imagen (excel)")
        (redcap0,) = por_regla(inicial, "QR-NUL-03", "bridge_atencion_imagen (redcap)")
        (total0,) = por_regla(inicial, "QR-NUL-03", "bridge_atencion_imagen (total)")
        assert total0.incumplen == excel0.incumplen + redcap0.incumplen
        assert total0.evaluadas == excel0.evaluadas + redcap0.evaluadas
        (excel1,) = por_regla(final, "QR-NUL-03", "bridge_atencion_imagen (excel)")
        (redcap1,) = por_regla(final, "QR-NUL-03", "bridge_atencion_imagen (redcap)")
        (total1,) = por_regla(final, "QR-NUL-03", "bridge_atencion_imagen (total)")
        assert (excel1.incumplen, redcap1.incumplen, total1.incumplen) == (
            excel0.incumplen + 1, redcap0.incumplen, total0.incumplen + 1)


class TestValidez:
    def test_tc_cal_17_rangos_cumplen_y_detecta_valores_fuera_de_rango(self, conexion, contrato):
        """
        Que es: prueba de calidad de las reglas QR-DOM-01 (Glasgow) y QR-DOM-02 (demás medidas).
        Que hace: verifica los rangos sobre la bodega sintética; luego deja un Glasgow ocular de 5, una temperatura de
                  60 y unos días de hospitalización negativos en atenciones distintas.
        Esperado: al inicio ninguna medida fuera de rango; después, 1 incumplimiento en cada una de esas tres.
        """
        # Arrange
        inicial = verificar_rangos(conexion, contrato)
        for columna, valor in (("gcs_ocular", 5), ("temperatura_c", 60), ("dias_hospitalizacion", -1)):
            conexion.execute(text(f"UPDATE trauma_completo.fact_trauma SET {columna} = {valor} "
                                  f"WHERE trauma_register_id = {_una_con(columna)}"))

        # Act
        final = verificar_rangos(conexion, contrato)

        # Assert
        assert all(r.cumple for r in inicial) and any(r.evaluadas > 0 for r in inicial)
        assert {r.regla for r in inicial} == {"QR-DOM-01", "QR-DOM-02"}
        for regla, columna in (("QR-DOM-01", "gcs_ocular"), ("QR-DOM-02", "temperatura_c"),
                               ("QR-DOM-02", "dias_hospitalizacion")):
            (afectada,) = por_regla(final, regla, f"fact_trauma.{columna} ")
            assert afectada.incumplen == 1
        assert sum(r.incumplen for r in final) == 3

    def test_tc_cal_18_cuenta_lo_registrado_sin_codigo_cie_10(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-DOM-03 (CIE-10 sin código, informativa).
        Que hace: cuenta, por puente y rol, las filas que apuntan a 'SIN CODIGO CIE-10'.
        Esperado: en el diagnóstico y en las complicaciones hay 2 filas sin código (los dos textos distintos sin pareja de
                  los casos del Excel; la repetición exacta se unió), sobre el total de filas de cada puente.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_cie10_sin_codigo(conexion, contrato)

        # Assert
        (diagnostico,) = por_regla(resultados, "QR-DOM-03", "bridge_atencion_cie_10[diagnostico]")
        (complicacion,) = por_regla(resultados, "QR-DOM-03", "bridge_atencion_complicacion")
        assert diagnostico.incumplen == 2 and diagnostico.evaluadas > 2
        assert complicacion.incumplen == 2 and complicacion.evaluadas > 2

    def test_tc_cal_35_valores_fuera_de_la_lista_permitida(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-DOM-04 (valores permitidos de un atributo de dimensión, advierte).
        Que hace: toma los valores sintéticos de `dim_paciente.genero` y verifica el atributo con la lista completa y luego
                  con la lista sin uno de ellos.
        Esperado: con la lista completa 0 incumplimientos; sin uno, incumplen los miembros que tienen ese valor y las
                  evaluadas no cambian (ni 'Sin dato' ni 'No aplica' cuentan). Con una dimensión sin lista no hay resultado.
        """
        # Arrange: los valores del atributo en la bodega sintética (sin los miembros por defecto)
        valores = [v for (v,) in conexion.execute(text(
            "SELECT DISTINCT genero FROM trauma_completo.dim_paciente WHERE genero NOT IN ('Sin dato', 'No aplica') "
            "ORDER BY 1")).all()]
        omitido = valores[0]
        con_el_omitido = conexion.execute(text(
            "SELECT count(*) FROM trauma_completo.dim_paciente WHERE genero = :v"), {"v": omitido}).scalar()

        # Act
        completa = verificar_valores_permitidos(conexion, contrato, {"dim_paciente": {"genero": valores}})
        incompleta = verificar_valores_permitidos(conexion, contrato, {"dim_paciente": {"genero": valores[1:] or ["-"]}})
        sin_lista = verificar_valores_permitidos(conexion, contrato, {})

        # Assert
        (cumple,) = por_regla(completa, "QR-DOM-04", "dim_paciente.genero")
        (no_cumple,) = por_regla(incompleta, "QR-DOM-04", "dim_paciente.genero")
        assert cumple.evaluadas > 0 and cumple.incumplen == 0
        assert (no_cumple.evaluadas, no_cumple.incumplen) == (cumple.evaluadas, con_el_omitido)
        assert sin_lista == []


class TestConsistencia:
    def test_tc_cal_19_cumple_en_la_bodega_cargada(self, conexion, contrato):
        """
        Que es: prueba de calidad de las reglas QR-CON-01 a 06, caso que cumple.
        Que hace: verifica el orden de las fechas, las horas con su fecha, las fechas futuras y la coherencia de presiones y
                  días de UCI sobre la bodega sintética.
        Esperado: aparecen las seis reglas, con filas evaluadas en el orden de las fechas, y ninguna incumple.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_consistencia(conexion, contrato, hoy=HOY)

        # Assert
        assert {r.regla for r in resultados} == {f"QR-CON-0{n}" for n in range(1, 7)}
        (alta,) = por_regla(resultados, "QR-CON-01")
        assert alta.evaluadas > 0
        assert all(r.cumple for r in resultados)

    def test_tc_cal_19_detecta_cada_incoherencia(self, conexion, contrato):
        """
        Que es: prueba de calidad de las reglas QR-CON-01 a 06, casos defectuosos.
        Que hace: en cuatro atenciones distintas, pone el alta al inicio del calendario (antes de la admisión), deja una
                  hora de alta sin su fecha, deja la presión diastólica sobre la sistólica y los días de UCI sobre los de
                  hospitalización.
        Esperado: QR-CON-01, 03, 05 y 06 reportan exactamente 1 fila incumplida cada una; las fechas de esas atenciones
                  no son futuras (QR-CON-04 en 0).
        """
        # Arrange: un defecto por atención, en columnas independientes entre sí
        sql = "UPDATE trauma_completo.fact_trauma SET {cambio} WHERE trauma_register_id = {donde}"
        dia = "(SELECT tiempo_id FROM trauma_completo.dim_tiempo WHERE fecha = '{}')"
        for cambio, columna in (
                (f"fecha_alta_id = {dia.format('2011-01-01')}", "fecha_alta_id"),
                ("fecha_alta_id = NULL", "hora_alta_id"),
                ("presion_diastolica = presion_sistolica + 10", "presion_sistolica"),
                ("uci_dias = dias_hospitalizacion + 1", "dias_hospitalizacion")):
            # Cada defecto va en una atención distinta, para que no se pisen
            conexion.execute(text(sql.format(cambio=cambio, donde=_distinta(conexion, columna))))

        # Act
        resultados = {(r.regla, r.detalle): r.incumplen for r in verificar_consistencia(conexion, contrato, hoy=HOY)}

        # Assert
        assert resultados[("QR-CON-01", "alta no anterior a la admisión")] == 1
        assert resultados[("QR-CON-03", "fact_trauma.hora_alta_id con su fecha")] == 1
        assert resultados[("QR-CON-05", "presión diastólica no mayor que la sistólica")] == 1
        assert resultados[("QR-CON-06", "días de UCI no mayores que los de hospitalización")] == 1
        assert resultados[("QR-CON-04", "fact_trauma.fecha_admision_id no posterior a hoy")] == 0

    def test_tc_cal_19_detecta_una_fecha_futura(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-CON-04 (fechas no posteriores a hoy), caso defectuoso.
        Que hace: mueve la fecha de admisión de una atención a mediados de 2027, posterior al día de la carga.
        Esperado: la fecha de admisión reporta 1 fila futura y las otras dos fechas del hecho, 0.
        """
        # Arrange
        conexion.execute(text(
            "UPDATE trauma_completo.fact_trauma SET fecha_admision_id = "
            "(SELECT tiempo_id FROM trauma_completo.dim_tiempo WHERE fecha = '2027-06-01') "
            f"WHERE trauma_register_id = {PRIMERA_ATENCION}"))

        # Act
        resultados = verificar_consistencia(conexion, contrato, hoy=HOY)

        # Assert
        futuras = {r.detalle.split(".")[1].split(" ")[0]: r.incumplen for r in por_regla(resultados, "QR-CON-04")}
        assert futuras == {"fecha_admision_id": 1, "fecha_hospitalizacion_id": 0, "fecha_alta_id": 0}


class TestTiempoCompleto:
    def test_tc_cal_20_cumple_y_detecta_un_dia_faltante(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-TIE-01 (calendario y horario completos).
        Que hace: verifica el horario (1 440 minutos) y el calendario (días consecutivos desde 2011-01-01); luego borra un
                  día que ningún hecho usa.
        Esperado: al inicio 0 incumplimientos en las dos verificaciones; después, el calendario reporta 1 día faltante y el
                  horario sigue en 0.
        """
        # Arrange
        inicial = verificar_tiempo_completo(conexion, contrato)
        conexion.execute(text("DELETE FROM trauma_completo.dim_tiempo WHERE fecha = '2012-02-15'"))

        # Act
        final = verificar_tiempo_completo(conexion, contrato)

        # Assert
        assert len(inicial) == 2 and all(r.cumple for r in inicial)
        (horario,) = por_regla(final, "QR-TIE-01", "dim_horario")
        (calendario,) = por_regla(final, "QR-TIE-01", "dim_tiempo")
        assert (horario.incumplen, calendario.incumplen) == (0, 1)


def _distinta(conexion, columna: str) -> str:
    """Una atención con la columna con valor, distinta en cada llamada (las ya usadas se anotan en la conexión)."""
    usadas = conexion.info.setdefault("usadas", [])
    clave = conexion.execute(text(
        "SELECT min(trauma_register_id) FROM trauma_completo.fact_trauma WHERE "
        f"{columna} IS NOT NULL AND fecha_admision_id IS NOT NULL AND trauma_register_id <> ALL(:usadas)"),
        {"usadas": usadas or ["-"]}).scalar()
    usadas.append(clave)
    return f"'{clave}'"
