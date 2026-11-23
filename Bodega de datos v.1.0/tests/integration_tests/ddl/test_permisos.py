"""
TC-DDL-07, TC-DDL-10 y parte de TC-DDL-08: permisos del rol lector (el que usaria Power BI).

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Convencion: codigo_lector(sql) ejecuta la sentencia conectado COMO LECTOR y devuelve el SQLSTATE
del error (42501 = insufficient_privilege, permiso denegado), o None si la sentencia se ejecuto
sin error. Las tablas de la base de pruebas estan vacias: una lectura permitida devuelve cero filas
pero no falla.
"""
import re

import pytest
from sqlalchemy import text

from tests.integration_tests.ddl.constantes import PERMISO_DENEGADO, RAIZ


def _columnas_excluidas():
    """Lee del propio 04_permissions.sql la lista esquema.tabla.columna que el lector no debe ver."""
    sql = (RAIZ / "database" / "schema" / "04_permissions.sql").read_text(encoding="utf-8")
    bloque = sql.split("ARRAY[", 1)[1].split("];", 1)[0]
    sin_comentarios = "\n".join(l for l in bloque.splitlines() if not l.strip().startswith("--"))
    return re.findall(r"'([a-z_0-9]+\.[a-z_0-9]+\.[a-z_0-9]+)'", sin_comentarios)


# ---------------------------------------------------------------- TC-DDL-07
def test_tc_ddl_07_lector_puede_leer_columnas_permitidas(codigo_lector):
    """
    Que es: prueba de control positivo de los permisos de lectura.
    Que hace: como lector, consulta columnas no sensibles del hecho, tablas completas sin exclusiones
              (un puente y dos dimensiones), las columnas permitidas del puente CIE-10 (todo menos texto_origen) y
              las columnas permitidas del hecho del mini.
    Esperado: ninguna consulta falla (todas devuelven None).
    """
    # Arrange: consultas que el lector debe poder ejecutar
    consultas = [
        "SELECT peso, gcs_motor, trauma_register_id FROM trauma_completo.fact_trauma",
        "SELECT * FROM trauma_completo.bridge_atencion_lesion",
        "SELECT fact_id, cie_10_id, rol FROM trauma_completo.bridge_atencion_cie_10",
        "SELECT * FROM trauma_completo.dim_paciente",
        "SELECT id, trauma_register_record_id FROM trauma_mini.dwh_dim_hechos",
        "SELECT * FROM trauma_mini.dwh_dim_calendario",
    ]

    # Act
    resultados = {consulta: codigo_lector(consulta) for consulta in consultas}

    # Assert: se muestra cual consulta fallo, si alguna lo hace
    fallidas = {consulta: codigo for consulta, codigo in resultados.items() if codigo is not None}
    assert fallidas == {}


def test_tc_ddl_07_lista_de_columnas_excluidas_no_esta_vacia():
    """
    Que es: prueba de seguridad de la propia prueba (no usa la base de datos).
    Que hace: lee la lista de columnas excluidas de 04_permissions.sql.
    Esperado: la lista tiene al menos una columna; si quedara vacia, las pruebas parametrizadas de
              abajo no comprobarian nada y pasarian en falso.
    """
    # Arrange: la lista se lee del propio script de permisos

    # Act
    columnas = _columnas_excluidas()

    # Assert
    assert len(columnas) >= 1


@pytest.mark.parametrize("columna", _columnas_excluidas())
def test_tc_ddl_07_lector_no_puede_leer_columnas_excluidas(codigo_lector, columna):
    """
    Que es: prueba de proteccion de datos sensibles (Habeas Data); una ejecucion por cada columna
            de la lista de exclusion de 04_permissions.sql (direcciones y texto clinico libre).
    Que hace: como lector, hace SELECT de esa columna.
    Esperado: la consulta falla con 42501 (permiso denegado).
    """
    # Arrange: la columna llega como esquema.tabla.columna
    esquema, tabla, campo = columna.split(".")

    # Act
    resultado = codigo_lector(f"SELECT {campo} FROM {esquema}.{tabla}")

    # Assert
    assert resultado == PERMISO_DENEGADO


def test_tc_ddl_07_select_asterisco_falla_en_tablas_con_columnas_excluidas(codigo_lector):
    """
    Que es: prueba de que las exclusiones no se saltan con SELECT *.
    Que hace: como lector, hace SELECT * sobre el hecho del completo (tiene columnas excluidas) y sobre el
              del mini (desde 2026-10-24 no tiene ninguna: motivo_de_consulta lo requiere el tablero).
    Esperado: la del completo falla con 42501; la del mini funciona (None).
    """
    # Arrange: solo el hecho del completo conserva columnas excluidas
    consulta_completo = "SELECT * FROM trauma_completo.fact_trauma"
    consulta_mini = "SELECT * FROM trauma_mini.dwh_dim_hechos"

    # Act
    resultado_completo = codigo_lector(consulta_completo)
    resultado_mini = codigo_lector(consulta_mini)

    # Assert
    assert resultado_completo == PERMISO_DENEGADO
    assert resultado_mini is None


@pytest.mark.parametrize(
    "sentencia",
    [
        "INSERT INTO trauma_completo.dim_caida DEFAULT VALUES",
        "UPDATE trauma_completo.dim_caida SET caida = 'x'",
        "DELETE FROM trauma_completo.dim_caida",
        "TRUNCATE trauma_completo.dim_caida",
        "INSERT INTO trauma_mini.dwh_dim_municipio (nombre) VALUES ('x')",
        "CREATE TABLE trauma_completo.tabla_intrusa (a integer)",
        "CREATE TABLE trauma_mini.tabla_intrusa (a integer)",
        "DROP TABLE trauma_completo.dim_caida",
        "ALTER TABLE trauma_completo.dim_caida ADD COLUMN x integer",
    ],
)
def test_tc_ddl_07_lector_no_puede_escribir_ni_modificar(codigo_lector, sentencia):
    """
    Que es: prueba de que el lector es de solo lectura; una ejecucion por cada sentencia de la lista
            (INSERT, UPDATE, DELETE, TRUNCATE, CREATE TABLE, DROP TABLE y ALTER TABLE).
    Que hace: como lector, intenta ejecutar la sentencia sobre los esquemas de los modelos.
    Esperado: todas fallan con 42501 (permiso denegado).
    """
    # Arrange: la sentencia de escritura o modificacion llega por parametro

    # Act
    resultado = codigo_lector(sentencia)

    # Assert
    assert resultado == PERMISO_DENEGADO


# ---------------------------------------------------------------- TC-DDL-08 (esquema de control)
def test_tc_ddl_08_el_lector_no_accede_al_esquema_de_control(codigo_lector):
    """
    Que es: prueba de aislamiento del esquema etl_control (metadatos operativos del ETL).
    Que hace: como lector, intenta leer e insertar en etl_control.extraccion.
    Esperado: ambas sentencias fallan con 42501; el lector no tiene acceso ni al esquema.
    """
    # Arrange: una lectura y una escritura sobre la tabla de control
    leer = "SELECT * FROM etl_control.extraccion"
    escribir = "INSERT INTO etl_control.extraccion (fuente, filas_extraidas, exitosa) VALUES ('x', 1, true)"

    # Act
    resultado_lectura = codigo_lector(leer)
    resultado_escritura = codigo_lector(escribir)

    # Assert
    assert resultado_lectura == PERMISO_DENEGADO
    assert resultado_escritura == PERMISO_DENEGADO


# ---------------------------------------------------------------- TC-DDL-10 (todo el esquema de control)
def test_tc_ddl_10_el_lector_no_accede_a_ninguna_tabla_de_etl_control(conexion, bd_prueba, codigo_lector):
    """
    Que es: prueba de aislamiento de todas las tablas de etl_control, incluidas las que se agreguen después.
    Que hace: lista las tablas del esquema como dueño; consulta si el lector tiene USAGE sobre el esquema; y como
              lector, intenta leer cada tabla y ejecutar una escritura que no toca ninguna fila (DELETE ... WHERE false).
    Esperado: el esquema tiene al menos las cuatro tablas conocidas (extraccion, carga, carga_detalle y calidad); el lector
              no tiene USAGE; y toda lectura y toda escritura fallan con 42501 (permiso denegado).
    """
    # Arrange: tablas del esquema vistas por el dueño; el rol lector sale de la configuración de la base de pruebas
    tablas = set(conexion.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'etl_control' AND table_type = 'BASE TABLE'")).scalars().all())

    # Act
    tiene_usage = conexion.execute(text("SELECT has_schema_privilege(:lector, 'etl_control', 'USAGE')"),
                                   {"lector": bd_prueba["reader"]}).scalar_one()
    lecturas = {t: codigo_lector(f"SELECT * FROM etl_control.{t}") for t in sorted(tablas)}
    escrituras = {t: codigo_lector(f"DELETE FROM etl_control.{t} WHERE false") for t in sorted(tablas)}

    # Assert: la lista no puede estar vacía (la prueba pasaría sin comprobar nada) y nada se permite
    assert {"extraccion", "carga", "carga_detalle", "calidad"} <= tablas
    assert tiene_usage is False
    assert {t: c for t, c in lecturas.items() if c != PERMISO_DENEGADO} == {}
    assert {t: c for t, c in escrituras.items() if c != PERMISO_DENEGADO} == {}
