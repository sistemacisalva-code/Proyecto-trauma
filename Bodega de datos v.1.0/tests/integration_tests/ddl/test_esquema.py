"""
TC-DDL-01, TC-DDL-02, TC-DDL-12 y parte de TC-DDL-08: existencia de los esquemas,
idempotencia del arranque y lista de modelos activos.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
"""
from sqlalchemy import text

import main
from tests.integration_tests.ddl.constantes import COMPLETO, MINI, PERMISO_DENEGADO


def _tablas(conexion, esquema):
    """Devuelve el conjunto de nombres de tablas base de un esquema (consulta information_schema)."""
    filas = conexion.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :e AND table_type = 'BASE TABLE'"
        ),
        {"e": esquema},
    )
    return set(filas.scalars().all())


def _huella_del_esquema(motor):
    """Devuelve (numero de tablas, de restricciones, de indices) de los esquemas trauma_* y etl_control."""
    with motor.connect() as c:
        return c.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM information_schema.tables
                    WHERE (table_schema LIKE 'trauma\\_%' OR table_schema = 'etl_control')
                      AND table_type = 'BASE TABLE'),
                  (SELECT count(*) FROM pg_constraint k JOIN pg_namespace n ON n.oid = k.connamespace
                    WHERE n.nspname LIKE 'trauma\\_%' OR n.nspname = 'etl_control'),
                  (SELECT count(*) FROM pg_indexes
                    WHERE schemaname LIKE 'trauma\\_%' OR schemaname = 'etl_control')
                """
            )
        ).one()


# ---------------------------------------------------------------- TC-DDL-01
def test_tc_ddl_01_tablas_del_modelo_completo(conexion):
    """
    Que es: prueba de existencia del esquema trauma_completo.
    Que hace: lista las tablas base del esquema en la base de pruebas.
    Esperado: exactamente las 24 tablas del modelo (6 puentes, 17 dimensiones y catalogos, y el hecho),
              sin ninguna de mas ni de menos.
    """
    # Arrange: la base de pruebas ya fue creada con el DDL real por el fixture bd_prueba

    # Act
    tablas = _tablas(conexion, "trauma_completo")

    # Assert
    assert tablas == COMPLETO


def test_tc_ddl_01_tablas_del_modelo_mini(conexion):
    """
    Que es: prueba de existencia del esquema trauma_mini.
    Que hace: lista las tablas base del esquema en la base de pruebas.
    Esperado: exactamente las 7 tablas del modelo mini (hecho, 5 dimensiones y la subdimension).
    """
    # Arrange: la base de pruebas ya fue creada con el DDL real por el fixture bd_prueba

    # Act
    tablas = _tablas(conexion, "trauma_mini")

    # Assert
    assert tablas == MINI


def test_tc_ddl_01_esquema_de_control_del_etl(conexion):
    """
    Que es: prueba de existencia del esquema etl_control.
    Que hace: lista sus tablas y las columnas de etl_control.extraccion, etl_control.carga,
              etl_control.carga_detalle y etl_control.calidad.
    Esperado: exactamente cuatro tablas (extraccion, carga, carga_detalle y calidad); calidad con id, modelo,
              el veredicto, los tres conteos de reglas, la carpeta del reporte y ejecutado_en; extraccion con id, fuente,
              filas_extraidas, exitosa y ejecutado_en; carga con id, modelo, fuente, run_id_staging, filas_origen,
              filas_cargadas, filas_no_usadas, filas_cuarentena, la carpeta de la cuarentena, los cuatro conteos de atenciones de la carga
              incremental (nuevas, modificadas, sin cambio y eliminadas), exitosa y ejecutado_en; carga_detalle
              con la corrida, el uso (destino y tabla de staging) y los seis conteos del balance.
    """
    # Arrange: la base de pruebas ya fue creada con el DDL real por el fixture bd_prueba
    consulta = text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'etl_control' AND table_name = :t"
    )

    # Act
    tablas = _tablas(conexion, "etl_control")
    columnas_extraccion = set(conexion.execute(consulta, {"t": "extraccion"}).scalars().all())
    columnas_carga = set(conexion.execute(consulta, {"t": "carga"}).scalars().all())
    columnas_detalle = set(conexion.execute(consulta, {"t": "carga_detalle"}).scalars().all())
    columnas_calidad = set(conexion.execute(consulta, {"t": "calidad"}).scalars().all())

    # Assert
    assert tablas == {"extraccion", "carga", "carga_detalle", "calidad"}
    assert columnas_calidad == {"id", "modelo", "veredicto", "reglas_cumplen", "reglas_advierten", "reglas_fallan",
                                "ruta_reporte", "ejecutado_en"}
    assert columnas_extraccion == {"id", "fuente", "filas_extraidas", "exitosa", "ejecutado_en"}
    assert columnas_carga == {"id", "modelo", "fuente", "run_id_staging", "filas_origen", "filas_cargadas",
                              "filas_no_usadas", "filas_cuarentena", "atenciones_nuevas", "atenciones_modificadas",
                              "atenciones_sin_cambio", "atenciones_eliminadas", "ruta_cuarentena", "exitosa",
                              "ejecutado_en"}
    assert columnas_detalle == {"carga_id", "destino", "tabla_staging", "leidas", "cargadas", "otra_toma",
                                "sin_valor", "duplicado", "cuarentena"}


# ---------------------------------------------------------------- TC-DDL-02
def test_tc_ddl_02_ejecutar_main_dos_veces_no_falla(bd_prueba, motor_app):
    """
    Que es: prueba de idempotencia del arranque (main.py).
    Que hace: mide tablas, restricciones e indices, vuelve a ejecutar main.inicializar_bodega_de_datos()
              sobre la misma base y los mide otra vez.
    Esperado: la segunda ejecucion termina sin excepcion y las tres cifras son identicas
              (no se duplica ni se pierde ningun objeto).
    """
    # Arrange: medicion de la base tal como la dejo la primera ejecucion
    antes = _huella_del_esquema(motor_app)

    # Act: segunda ejecucion completa del arranque (si falla, la excepcion hace fallar la prueba)
    main.inicializar_bodega_de_datos()
    despues = _huella_del_esquema(motor_app)

    # Assert
    assert despues == antes


# ---------------------------------------------------------------- TC-DDL-08 (lista de scripts)
def test_tc_ddl_08_quitar_un_modelo_no_afecta_al_esquema_de_control():
    """
    Que es: prueba de la configuracion de scripts de main.py (no usa la base de datos).
    Que hace: revisa las listas SCRIPTS_CONTROL y SCRIPTS_DDL.
    Esperado: el script del esquema de control esta en ambas, es decir, no depende de MODELOS_ACTIVOS.
    """
    # Arrange: las listas se construyen al importar main

    # Act
    control = set(main.SCRIPTS_CONTROL)
    ddl = set(main.SCRIPTS_DDL)

    # Assert
    assert "02_etl_control.sql" in control
    assert control <= ddl


# ---------------------------------------------------------------- TC-DDL-12
# Va al final: borra un esquema y lo restaura. No depende del orden, pero es la mas costosa.
def test_tc_ddl_12_quitar_un_modelo_no_rompe_ddl_ni_permisos(bd_prueba, motor_app, codigo_lector, monkeypatch):
    """
    Que es: prueba de escenario, quitar el modelo completo de MODELOS_ACTIVOS.
    Que hace: borra el esquema trauma_completo, deja solo el mini en la configuracion de main,
              re-ejecuta el DDL y los permisos, y consulta como lector. Al terminar restaura
              la configuracion y reconstruye la base con los dos modelos.
    Esperado: el DDL y los permisos se aplican sin error; solo existe trauma_mini; el lector puede
              leer el hecho del mini (incluido motivo_de_consulta, permitido desde 2026-10-24) y sigue
              sin poder escribir en el (solo lectura).
    """
    try:
        # Arrange: el esquema del modelo completo desaparece y main queda configurado solo con el mini
        with motor_app.begin() as c:
            c.execute(text("DROP SCHEMA trauma_completo CASCADE"))
        monkeypatch.setattr(main, "MODELOS_ACTIVOS", ["mini"])
        monkeypatch.setattr(main, "ESQUEMAS", ["trauma_mini"])
        monkeypatch.setattr(main, "SCRIPTS_DDL", ["02_tables_mini.sql", "03_indexes_mini.sql"])

        # Act: se vuelve a aplicar el DDL y los permisos, y se consulta el resultado
        main.aplicar_esquemas_dimensionales(bd_prueba)
        main.aplicar_permisos(bd_prueba)
        with motor_app.connect() as c:
            esquemas = set(
                c.execute(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'trauma\\_%'")).scalars().all()
            )
        lectura_permitida = codigo_lector(
            "SELECT id, trauma_register_record_id, motivo_de_consulta FROM trauma_mini.dwh_dim_hechos"
        )
        escritura = codigo_lector("INSERT INTO trauma_mini.dwh_dim_municipio (nombre) VALUES ('x')")
    finally:
        # Se restaura el entorno aunque algo falle, para no afectar a las demas pruebas
        monkeypatch.undo()
        main.inicializar_bodega_de_datos()

    # Assert
    assert esquemas == {"trauma_mini"}
    assert lectura_permitida is None
    assert escritura == PERMISO_DENEGADO
