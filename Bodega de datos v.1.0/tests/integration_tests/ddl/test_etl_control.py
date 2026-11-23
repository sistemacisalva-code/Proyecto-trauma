"""
TC-DDL-08 y TC-DDL-09: tablas etl_control.extraccion, etl_control.carga, etl_control.carga_detalle y etl_control.calidad (valores por
defecto, restricciones, reconciliacion de la carga por uso y consultas de la guardia).

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Convencion: codigo_error(sql) ejecuta la sentencia y devuelve el SQLSTATE del error
(428C9 = generated_always, 23502 = not_null_violation, 23514 = check_violation),
o None si la sentencia se ejecuto sin error. Todo lo que se inserta se revierte al terminar cada prueba.
"""
from sqlalchemy import text

from tests.integration_tests.ddl.constantes import CHECK_VIOLATION, FOREIGN_KEY, GENERATED_ALWAYS, NOT_NULL, UNIQUE


def test_tc_ddl_08_registro_de_corrida_usa_valores_por_defecto(conexion):
    """
    Que es: prueba de control positivo, registrar una corrida del ETL.
    Que hace: inserta una fila con solo fuente, filas_extraidas y exitosa, y pide id y ejecutado_en.
    Esperado: la insercion funciona; el id es un entero generado y ejecutado_en trae la fecha y hora
              actuales (DEFAULT now()) aunque no se indico.
    """
    # Arrange: insercion que no menciona ni el id ni la fecha
    insertar = (
        "INSERT INTO etl_control.extraccion (fuente, filas_extraidas, exitosa) "
        "VALUES ('excel:historico', 120, true) RETURNING id, ejecutado_en"
    )

    # Act
    fila = conexion.execute(text(insertar)).one()

    # Assert
    assert isinstance(fila.id, int)
    assert fila.ejecutado_en is not None


def test_tc_ddl_08_restricciones_de_la_tabla_de_control(codigo_error):
    """
    Que es: prueba de las restricciones de etl_control.extraccion.
    Que hace: intenta insertar una clave explicita, una fila sin fuente, una sin filas_extraidas
              y una con filas_extraidas negativas.
    Esperado: 428C9 (clave explicita), 23502 (sin fuente), 23502 (sin filas_extraidas)
              y 23514 (filas negativas, viola el CHECK).
    """
    # Arrange: cuatro inserciones invalidas, cada una viola una restriccion distinta
    con_clave = "INSERT INTO etl_control.extraccion (id, fuente, filas_extraidas, exitosa) VALUES (99, 'x', 1, true)"
    sin_fuente = "INSERT INTO etl_control.extraccion (filas_extraidas, exitosa) VALUES (1, true)"
    sin_filas = "INSERT INTO etl_control.extraccion (fuente, exitosa) VALUES ('x', true)"
    filas_negativas = "INSERT INTO etl_control.extraccion (fuente, filas_extraidas, exitosa) VALUES ('x', -1, true)"

    # Act
    error_clave = codigo_error(con_clave)
    error_fuente = codigo_error(sin_fuente)
    error_filas = codigo_error(sin_filas)
    error_negativas = codigo_error(filas_negativas)

    # Assert
    assert error_clave == GENERATED_ALWAYS
    assert error_fuente == NOT_NULL
    assert error_filas == NOT_NULL
    assert error_negativas == CHECK_VIOLATION


def test_tc_ddl_08_conteos_de_atenciones_de_la_carga_incremental(conexion, codigo_error):
    """
    Que es: prueba de los conteos de atenciones de etl_control.carga (carga incremental).
    Que hace: inserta una corrida sin mencionarlos y otra con un conteo negativo.
    Esperado: sin mencionarlos, los cuatro quedan en 0 (DEFAULT) y la reconciliacion de filas no los usa; el
              negativo falla con 23514 (check_violation).
    """
    # Arrange: corrida minima que reconcilia (100 = 90 + 8 + 2) y la misma con atenciones_nuevas negativas
    base = ("INSERT INTO etl_control.carga (modelo, fuente, run_id_staging, filas_origen, filas_cargadas, "
            "filas_no_usadas, filas_cuarentena, ruta_cuarentena, exitosa{extra}) VALUES ('completo', 'redcap', 'run', "
            "100, 90, 8, 2, 'cuarentena/sintetica', true{valor})")

    # Act
    fila = conexion.execute(text(base.format(extra="", valor="") + " RETURNING atenciones_nuevas, "
                                 "atenciones_modificadas, atenciones_sin_cambio, atenciones_eliminadas")).one()
    negativo = codigo_error(base.format(extra=", atenciones_nuevas", valor=", -1"))

    # Assert
    assert tuple(fila) == (0, 0, 0, 0)
    assert negativo == CHECK_VIOLATION


def test_tc_ddl_08_guardia_de_idempotencia_consulta_por_fuente(conexion):
    """
    Que es: prueba de la consulta que usara la guardia de idempotencia de etl/pipeline.py
            ("ya hubo una corrida exitosa para esta fuente?").
    Que hace: registra una corrida exitosa de 'excel:historico' y una fallida de 'redcap', y cuenta las
              corridas exitosas de cada fuente.
    Esperado: 1 para 'excel:historico' y 0 para 'redcap' (la corrida fallida no cuenta).
    """
    # Arrange: una corrida exitosa de excel y una fallida de redcap
    conexion.execute(
        text(
            "INSERT INTO etl_control.extraccion (fuente, filas_extraidas, exitosa) "
            "VALUES ('excel:historico', 10, true), ('redcap', 5, false)"
        )
    )
    consulta = text("SELECT count(*) FROM etl_control.extraccion WHERE fuente = :f AND exitosa")

    # Act
    exitosas_excel = conexion.execute(consulta, {"f": "excel:historico"}).scalar_one()
    exitosas_redcap = conexion.execute(consulta, {"f": "redcap"}).scalar_one()

    # Assert
    assert exitosas_excel == 1
    assert exitosas_redcap == 0


def test_tc_ddl_08_carga_exitosa_debe_reconciliar(codigo_error):
    """
    Que es: prueba de la regla QR-EXA-01 impuesta por la base en etl_control.carga (por uso).
    Que hace: registra una carga exitosa que cuadra con no usadas (100 = 90 + 8 + 2), una exitosa que no
              cuadra (100 != 89 + 8 + 2), una fallida que no cuadra y una con filas_no_usadas negativas.
    Esperado: la exitosa que cuadra y la fallida entran (una falla puede quedar a medias); la exitosa que no
              cuadra y la de filas negativas fallan con 23514 (check_violation).
    """
    # Arrange: la misma insercion con distintos conteos; modelo, fuente y run_id son sinteticos
    insertar = (
        "INSERT INTO etl_control.carga (modelo, fuente, run_id_staging, filas_origen, filas_cargadas, "
        "filas_no_usadas, filas_cuarentena, ruta_cuarentena, exitosa) "
        "VALUES ('completo', 'excel', '2026-01-01T000000', :o, :c, :n, :q, CASE WHEN :q > 0 THEN 'cuarentena/sintetica' END, :e)"
    )

    # Act
    exitosa_cuadra = codigo_error(insertar, o=100, c=90, n=8, q=2, e=True)
    exitosa_no_cuadra = codigo_error(insertar, o=100, c=89, n=8, q=2, e=True)
    fallida_no_cuadra = codigo_error(insertar, o=100, c=0, n=0, q=0, e=False)
    no_usadas_negativas = codigo_error(insertar, o=100, c=99, n=-1, q=2, e=True)

    # Assert
    assert exitosa_cuadra is None
    assert exitosa_no_cuadra == CHECK_VIOLATION
    assert fallida_no_cuadra is None
    assert no_usadas_negativas == CHECK_VIOLATION


def test_tc_ddl_08_detalle_por_uso_reconcilia_y_sigue_a_su_corrida(conexion, codigo_error):
    """
    Que es: prueba de etl_control.carga_detalle: balance por uso de una carga.
    Que hace: registra una corrida y le agrega un uso que cuadra (10 = 3 + 5 + 1 + 0 + 1), uno que no cuadra, uno
              con un conteo negativo, el mismo uso repetido y uno de una corrida inexistente; luego borra la
              corrida y cuenta su detalle.
    Esperado: el uso que cuadra entra; el que no cuadra y el negativo fallan con 23514; el repetido con 23505
              (unique_violation, la clave es corrida + destino + tabla); el de una corrida inexistente con 23503;
              al borrar la corrida no queda detalle (ON DELETE CASCADE).
    """
    # Arrange: una corrida sintetica y la insercion de un uso
    carga = conexion.execute(text(
        "INSERT INTO etl_control.carga (modelo, fuente, run_id_staging, filas_origen, filas_cargadas, "
        "filas_no_usadas, filas_cuarentena, ruta_cuarentena, exitosa) "
        "VALUES ('completo', 'redcap', 'r1', 10, 3, 6, 1, 'cuarentena/sintetica', true) "
        "RETURNING id"
    )).scalar_one()
    insertar = (
        "INSERT INTO etl_control.carga_detalle (carga_id, destino, tabla_staging, leidas, cargadas, otra_toma, "
        "sin_valor, duplicado, cuarentena) VALUES (:k, :d, 'signos_vitales', :l, :c, :o, :s, 0, :q)"
    )

    # Act
    cuadra = codigo_error(insertar, k=carga, d="fact_trauma", l=10, c=3, o=5, s=1, q=1)
    no_cuadra = codigo_error(insertar, k=carga, d="otro_destino", l=10, c=3, o=5, s=1, q=0)
    negativo = codigo_error(insertar, k=carga, d="tercer_destino", l=10, c=12, o=-1, s=0, q=-1)
    repetido = codigo_error(insertar, k=carga, d="fact_trauma", l=10, c=3, o=5, s=1, q=1)
    sin_corrida = codigo_error(insertar, k=999999, d="fact_trauma", l=1, c=1, o=0, s=0, q=0)
    conexion.execute(text("DELETE FROM etl_control.carga WHERE id = :k"), {"k": carga})
    restantes = conexion.execute(
        text("SELECT count(*) FROM etl_control.carga_detalle WHERE carga_id = :k"), {"k": carga}
    ).scalar_one()

    # Assert
    assert cuadra is None
    assert no_cuadra == CHECK_VIOLATION
    assert negativo == CHECK_VIOLATION
    assert repetido == UNIQUE
    assert sin_corrida == FOREIGN_KEY
    assert restantes == 0


def test_tc_ddl_08_guardia_de_carga_consulta_por_modelo_y_fuente(conexion):
    """
    Que es: prueba de la consulta que usara la guardia de la carga del Excel ("ya hubo una carga exitosa
            de esta fuente en este modelo?").
    Que hace: registra una carga exitosa de (completo, excel), una fallida de (mini, excel) y una exitosa de
              (completo, redcap); cuenta las exitosas de (completo, excel) y de (mini, excel).
    Esperado: 1 para (completo, excel) y 0 para (mini, excel): la guardia distingue el modelo y no cuenta fallas.
    """
    # Arrange: tres corridas con conteos que reconcilian
    conexion.execute(text(
        "INSERT INTO etl_control.carga (modelo, fuente, run_id_staging, filas_origen, filas_cargadas, "
        "filas_no_usadas, filas_cuarentena, exitosa) VALUES "
        "('completo', 'excel', 'r1', 10, 10, 0, 0, true), ('mini', 'excel', 'r1', 10, 0, 0, 0, false), "
        "('completo', 'redcap', 'r2', 5, 5, 0, 0, true)"
    ))
    consulta = text("SELECT count(*) FROM etl_control.carga WHERE modelo = :m AND fuente = 'excel' AND exitosa")

    # Act
    completo_excel = conexion.execute(consulta, {"m": "completo"}).scalar_one()
    mini_excel = conexion.execute(consulta, {"m": "mini"}).scalar_one()

    # Assert
    assert completo_excel == 1
    assert mini_excel == 0


def test_tc_ddl_09_veredicto_de_calidad_usa_valores_por_defecto_y_restricciones(conexion, codigo_error):
    """
    Que es: prueba de etl_control.calidad (veredicto del reporte de calidad de la bodega).
    Que hace: registra un veredicto sin id ni fecha; luego intenta un veredicto que no existe, un conteo negativo,
              una fila sin la carpeta del reporte y una clave explicita.
    Esperado: el primero entra con id entero generado y ejecutado_en por defecto (DEFAULT now()); el veredicto
              desconocido y el conteo negativo fallan con 23514 (check_violation); la fila sin carpeta con 23502
              (not_null_violation) y la clave explicita con 428C9 (generated_always).
    """
    # Arrange: la misma insercion con distintos valores; modelo y carpeta son sinteticos
    insertar = ("INSERT INTO etl_control.calidad (modelo, veredicto, reglas_cumplen, reglas_advierten, reglas_fallan, "
                "ruta_reporte) VALUES ('completo', :v, :c, 0, 0, :r)")

    # Act
    fila = conexion.execute(text(insertar + " RETURNING id, ejecutado_en"),
                            {"v": "Aprobada con advertencias", "c": 30, "r": "reportes/sintetico"}).one()
    veredicto_desconocido = codigo_error(insertar, v="Dudosa", c=30, r="reportes/sintetico")
    conteo_negativo = codigo_error(insertar, v="Aprobada", c=-1, r="reportes/sintetico")
    sin_carpeta = codigo_error(insertar, v="Aprobada", c=30, r=None)
    con_clave = codigo_error("INSERT INTO etl_control.calidad (id, modelo, veredicto, reglas_cumplen, reglas_advierten, "
                             "reglas_fallan, ruta_reporte) VALUES (99, 'completo', 'Aprobada', 1, 0, 0, 'r')")

    # Assert
    assert isinstance(fila.id, int) and fila.ejecutado_en is not None
    assert veredicto_desconocido == CHECK_VIOLATION
    assert conteo_negativo == CHECK_VIOLATION
    assert sin_carpeta == NOT_NULL
    assert con_clave == GENERATED_ALWAYS


def test_tc_ddl_11_ruta_de_la_cuarentena_solo_si_hubo_filas_apartadas(codigo_error):
    """
    Que es: prueba de la restriccion ck_carga_ruta_cuarentena de etl_control.carga (QR-TRZ-03).
    Que hace: registra cargas con y sin filas en cuarentena, con y sin carpeta de cuarentena, en las cuatro
              combinaciones, y una fallida con cuarentena y carpeta.
    Esperado: entran la carga con filas y carpeta, la que no tiene ninguna de las dos y la fallida con ambas; fallan con
              23514 (check_violation) la carga con filas en cuarentena y sin carpeta, y la que tiene carpeta sin filas.
    """
    # Arrange: la misma insercion con distintos valores; modelo, run_id y carpeta son sinteticos. La carga reconcilia
    # (10 = 8 + 0 + 2 o 10 = 10 + 0 + 0) para que solo la restriccion de la ruta pueda fallar
    insertar = ("INSERT INTO etl_control.carga (modelo, fuente, run_id_staging, filas_origen, filas_cargadas, "
                "filas_no_usadas, filas_cuarentena, ruta_cuarentena, exitosa) "
                "VALUES ('completo', 'redcap', 'r1', 10, :c, 0, :q, :r, :e)")

    # Act
    con_filas_y_ruta = codigo_error(insertar, c=8, q=2, r="cuarentena/sintetica", e=True)
    sin_filas_ni_ruta = codigo_error(insertar, c=10, q=0, r=None, e=True)
    fallida_con_ruta = codigo_error(insertar, c=0, q=2, r="cuarentena/sintetica", e=False)
    con_filas_sin_ruta = codigo_error(insertar, c=8, q=2, r=None, e=True)
    con_ruta_sin_filas = codigo_error(insertar, c=10, q=0, r="cuarentena/sintetica", e=True)

    # Assert
    assert (con_filas_y_ruta, sin_filas_ni_ruta, fallida_con_ruta) == (None, None, None)
    assert con_filas_sin_ruta == CHECK_VIOLATION
    assert con_ruta_sin_filas == CHECK_VIOLATION
