"""
TC-CAL-21 a TC-CAL-24, TC-CAL-31 y TC-CAL-34: ida y vuelta del hecho contra el staging (QR-EXA-04 y QR-EXA-02, etl/quality/origen.py) sobre la bodega
cargada con el staging sintético.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Las carpetas del staging son las mismas que cargó el fixture del módulo (sintéticas, sin datos reales); los defectos se
inyectan en el hecho dentro de la transacción de la prueba, que se revierte al terminar.
"""
from sqlalchemy import text

from etl.quality.origen import verificar_hecho_contra_staging
from tests.quality_tests.ayudas import por_regla

PRIMERA_DEL_EXCEL = "(SELECT min(trauma_register_id) FROM trauma_completo.fact_trauma WHERE trauma_register_id LIKE 'EX-%')"


class TestIdaYVueltaDelHecho:
    def test_tc_cal_21_la_bodega_coincide_con_el_staging(self, conexion, contrato, staging_dirs):
        """
        Que es: prueba de calidad de la regla QR-EXA-04 (ida y vuelta del hecho), caso que cumple.
        Que hace: compara, para cada fuente, las columnas copiadas y las fechas del hecho, la hora de alta y los atributos
                  de las dimensiones con los del staging cargado.
        Esperado: por fuente, el staging coincide con la carga, hay celdas, hora de alta y atributos evaluados, y ninguno
                  difiere.
        """
        # Arrange: bodega y staging cargados por los fixtures del módulo

        # Act
        resultados = verificar_hecho_contra_staging(conexion, contrato, staging_dirs)

        # Assert
        celdas = por_regla(resultados, "QR-EXA-04", "celdas")
        assert len(celdas) == 2 and all(r.evaluadas > 0 for r in celdas)
        horas = por_regla(resultados, "QR-EXA-04", "hora_alta_id")
        atributos = por_regla(resultados, "QR-EXA-04", "atributos de las dimensiones")
        assert len(horas) == 2 and len(atributos) == 2 and all(r.evaluadas > 0 for r in horas + atributos)
        assert all(r.cumple for r in resultados)

    def test_tc_cal_22_detecta_una_medida_y_una_fecha_alteradas(self, conexion, contrato, staging_dirs):
        """
        Que es: prueba de calidad de la regla QR-EXA-04, caso defectuoso (la carga se equivocó al copiar).
        Que hace: cambia el peso y la fecha de alta de una atención del Excel directamente en el hecho.
        Esperado: el Excel reporta 1 atención distinta en el peso y 1 en la fecha de alta, y 2 celdas en total; REDCap, 0.
        """
        # Arrange: el peso suma uno (o pasa de vacío a 1) y la fecha de alta se mueve al primer día del calendario
        conexion.execute(text(
            "UPDATE trauma_completo.fact_trauma SET peso = coalesce(peso, 0) + 1, "
            "fecha_alta_id = (SELECT tiempo_id FROM trauma_completo.dim_tiempo ORDER BY fecha LIMIT 1) "
            f"WHERE trauma_register_id = {PRIMERA_DEL_EXCEL}"))

        # Act
        resultados = verificar_hecho_contra_staging(conexion, contrato, staging_dirs)

        # Assert
        (peso,) = por_regla(resultados, "QR-EXA-04", "excel: fact_trauma.peso")
        (alta,) = por_regla(resultados, "QR-EXA-04", "excel: fact_trauma.fecha_alta_id")
        (excel,) = por_regla(resultados, "QR-EXA-04", "excel: celdas")
        (redcap,) = por_regla(resultados, "QR-EXA-04", "redcap: celdas")
        assert (peso.incumplen, alta.incumplen, excel.incumplen, redcap.incumplen) == (1, 1, 2, 0)

    def test_tc_cal_23_detecta_una_atencion_que_no_esta_en_el_staging(self, conexion, contrato, staging_dirs):
        """
        Que es: prueba de calidad de la regla QR-EXA-04, caso defectuoso (fila de la bodega sin origen).
        Que hace: cambia la llave de una atención del Excel por una que el staging no tiene.
        Esperado: el Excel reporta 1 atención de la bodega que no está en el staging.
        """
        # Arrange
        conexion.execute(text(
            "UPDATE trauma_completo.fact_trauma SET trauma_register_id = 'EX-999999' "
            f"WHERE trauma_register_id = {PRIMERA_DEL_EXCEL}"))

        # Act
        resultados = verificar_hecho_contra_staging(conexion, contrato, staging_dirs)

        # Assert
        (huerfana,) = por_regla(resultados, "QR-EXA-04", "excel: atenciones de la bodega que no están")
        assert huerfana.incumplen == 1

    def test_tc_cal_24_detecta_un_staging_que_no_es_el_de_la_carga(self, conexion, contrato, staging_dirs, tmp_path):
        """
        Que es: prueba de calidad de la regla QR-EXA-04, caso defectuoso (el staging cambió después de cargar).
        Que hace: da una carpeta inexistente para el Excel y cambia en la bitácora el run_id del staging de REDCap.
        Esperado: las dos fuentes reportan 1 incumplimiento de staging y no se comparan sus celdas.
        """
        # Arrange
        conexion.execute(text("UPDATE etl_control.carga SET run_id_staging = 'otro' WHERE fuente = 'redcap'"))
        carpetas = {"excel": str(tmp_path / "no_existe"), "redcap": staging_dirs["redcap"]}

        # Act
        resultados = verificar_hecho_contra_staging(conexion, contrato, carpetas)

        # Assert
        assert [r.incumplen for r in por_regla(resultados, "QR-EXA-04", "staging de la carga")] == [1, 1]
        assert por_regla(resultados, "QR-EXA-04", "celdas") == []

    def test_tc_cal_31_detecta_una_hora_de_alta_y_un_atributo_de_dimension_alterados(self, conexion, contrato, staging_dirs):
        """
        Que es: prueba de calidad de la regla QR-EXA-04, caso defectuoso en la hora de alta y en una dimensión.
        Que hace: cambia la hora de alta de una atención del Excel a las 23:59 y hace que su caída apunte al miembro
                  'No aplica' de dim_caida, directamente en el hecho.
        Esperado: el Excel reporta 1 atención distinta en la hora de alta y 1 en cada atributo de la caída (la caída y la
                  superficie), 2 en el total de atributos; REDCap, 0 en todo.
        """
        # Arrange: la atención de prueba llegó a otra hora y con una caída registrada; la hora y el miembro se cambian
        conexion.execute(text(
            "UPDATE trauma_completo.fact_trauma SET "
            "hora_alta_id = (SELECT horario_id FROM trauma_completo.dim_horario WHERE hora = 23 AND minuto = 59), "
            "caida_id = (SELECT caida_id FROM trauma_completo.dim_caida WHERE caida = 'No aplica') "
            f"WHERE trauma_register_id = {PRIMERA_DEL_EXCEL}"))

        # Act
        resultados = verificar_hecho_contra_staging(conexion, contrato, staging_dirs)

        # Assert
        (hora_excel,) = por_regla(resultados, "QR-EXA-04", "excel: fact_trauma.hora_alta_id")
        (hora_redcap,) = por_regla(resultados, "QR-EXA-04", "redcap: fact_trauma.hora_alta_id")
        (caida,) = por_regla(resultados, "QR-EXA-04", "excel: dim_caida.caida contra")
        (superficie,) = por_regla(resultados, "QR-EXA-04", "excel: dim_caida.tipo_superficie contra")
        (total_excel,) = por_regla(resultados, "QR-EXA-04", "excel: atributos de las dimensiones")
        (total_redcap,) = por_regla(resultados, "QR-EXA-04", "redcap: atributos de las dimensiones")
        assert (hora_excel.incumplen, hora_redcap.incumplen) == (1, 0)
        assert (caida.incumplen, superficie.incumplen) == (1, 1)
        assert (total_excel.incumplen, total_redcap.incumplen) == (2, 0)

    def test_tc_cal_34_las_atenciones_del_hecho_son_las_del_staging_menos_la_cuarentena(self, conexion, contrato, staging_dirs):
        """
        Que es: prueba de calidad de la regla QR-EXA-02 (atenciones del hecho = staging menos cuarentena), caso que cumple.
        Que hace: cuenta, por fuente, las atenciones de la tabla base del staging, resta las filas que la bitácora
                  registra en cuarentena para esa tabla y compara con las atenciones del hecho.
        Esperado: una verificación por fuente, con atenciones evaluadas y sin diferencia.
        """
        # Arrange: bodega y staging cargados por los fixtures del módulo

        # Act
        resultados = verificar_hecho_contra_staging(conexion, contrato, staging_dirs)

        # Assert
        atenciones = por_regla(resultados, "QR-EXA-02")
        assert sorted(r.detalle.split(":")[0] for r in atenciones) == ["excel", "redcap"]
        assert all(r.evaluadas > 0 and r.cumple for r in atenciones)

    def test_tc_cal_34_detecta_una_atencion_que_falta_en_el_hecho(self, conexion, contrato, staging_dirs):
        """
        Que es: prueba de calidad de la regla QR-EXA-02, caso defectuoso (la carga perdió una atención sin cuarentena).
        Que hace: borra del hecho una atención del Excel, que sigue en el staging y no está en cuarentena.
        Esperado: el Excel reporta 1 atención de diferencia; REDCap, 0.
        """
        # Arrange: los puentes de la atención caen con ella (ON DELETE CASCADE)
        conexion.execute(text(f"DELETE FROM trauma_completo.fact_trauma WHERE trauma_register_id = {PRIMERA_DEL_EXCEL}"))

        # Act
        resultados = verificar_hecho_contra_staging(conexion, contrato, staging_dirs)

        # Assert
        (excel,) = por_regla(resultados, "QR-EXA-02", "excel")
        (redcap,) = por_regla(resultados, "QR-EXA-02", "redcap")
        assert (excel.incumplen, redcap.incumplen) == (1, 0)
