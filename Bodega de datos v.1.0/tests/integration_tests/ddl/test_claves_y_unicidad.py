"""
TC-DDL-03 y TC-DDL-04: claves sustitutas GENERATED ALWAYS y restricciones de unicidad.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Convencion: codigo_error(sql) ejecuta la sentencia y devuelve el SQLSTATE del error
(por ejemplo "23505" = unique_violation), o None si la sentencia se ejecuto sin error.
Todo lo que se inserta se revierte al terminar cada prueba.
"""
import pytest
from sqlalchemy import text

from tests.integration_tests.ddl.constantes import (
    BRIDGES, CHECK_VIOLATION, COMPLETO, DIMENSIONES_SIN_CLAVE_NATURAL, GENERATED_ALWAYS, MINI, NOT_NULL,
    PUENTES_CON_CLAVE_SUSTITUTA, UNIQUE,
)


# ---------------------------------------------------------------- TC-DDL-03
def test_tc_ddl_03_todas_las_claves_sustitutas_son_generated_always(conexion):
    """
    Que es: prueba de definicion (metadatos) de las claves sustitutas.
    Que hace: consulta information_schema para ver que tablas tienen una columna GENERATED ALWAYS.
    Esperado: exactamente todas las dimensiones y los hechos de ambos modelos, mas bridge_atencion_cie_10 y
              bridge_atencion_complicacion (clave sustituta porque texto_origen admite NULL y va en su UNIQUE);
              ningun otro puente (sus claves son compuestas).
    """
    # Arrange: tablas que deben tener clave sustituta (todo menos los puentes de clave compuesta)
    con_sustituta = (COMPLETO - BRIDGES) | PUENTES_CON_CLAVE_SUSTITUTA
    esperadas = {f"trauma_completo.{t}" for t in con_sustituta} | {f"trauma_mini.{t}" for t in MINI}

    # Act
    con_identidad = set(
        conexion.execute(
            text(
                "SELECT table_schema || '.' || table_name FROM information_schema.columns "
                "WHERE table_schema LIKE 'trauma\\_%' AND identity_generation = 'ALWAYS'"
            )
        ).scalars().all()
    )

    # Assert
    assert con_identidad == esperadas


def test_tc_ddl_03_clave_explicita_es_rechazada(codigo_error):
    """
    Que es: prueba de comportamiento, insertar una clave sustituta a mano.
    Que hace: intenta un INSERT con valor explicito en la clave de una dimension de cada modelo.
    Esperado: PostgreSQL rechaza ambas con el codigo 428C9 (generated_always).
    """
    # Arrange: una insercion por modelo que trae la clave sustituta escrita a mano
    insertar_completo = "INSERT INTO trauma_completo.dim_paciente (paciente_id, genero) VALUES (999, 'F')"
    insertar_mini = "INSERT INTO trauma_mini.dwh_dim_municipio (id, nombre) VALUES (999, 'X')"

    # Act
    error_completo = codigo_error(insertar_completo)
    error_mini = codigo_error(insertar_mini)

    # Assert
    assert error_completo == GENERATED_ALWAYS
    assert error_mini == GENERATED_ALWAYS


def test_tc_ddl_03_sin_clave_explicita_la_base_la_genera(conexion):
    """
    Que es: prueba de control positivo (el caso normal de insercion).
    Que hace: inserta una fila sin indicar la clave y pide la clave con RETURNING.
    Esperado: la insercion funciona y devuelve un entero generado por la base de datos.
    """
    # Arrange: insercion que no menciona la clave sustituta
    insertar = "INSERT INTO trauma_completo.dim_paciente (genero) VALUES ('F') RETURNING paciente_id"

    # Act
    clave = conexion.execute(text(insertar)).scalar_one()

    # Assert
    assert isinstance(clave, int)


# ---------------------------------------------------------------- TC-DDL-04
@pytest.mark.parametrize("tabla", DIMENSIONES_SIN_CLAVE_NATURAL)
def test_tc_ddl_04_combinacion_totalmente_vacia_no_se_duplica(codigo_error, tabla):
    """
    Que es: prueba de UNIQUE NULLS NOT DISTINCT; se ejecuta una vez por cada una de las 9 dimensiones
            sin clave natural (7 del completo, 2 del mini).
    Que hace: inserta dos veces una fila con todos los atributos NULL (DEFAULT VALUES).
    Esperado: la primera insercion funciona (None); la segunda falla con 23505 (unique_violation),
              porque dos NULL cuentan como iguales.
    """
    # Arrange: insercion de una fila con todos los atributos en NULL
    insertar = f"INSERT INTO {tabla} DEFAULT VALUES"

    # Act
    primera = codigo_error(insertar)
    segunda = codigo_error(insertar)

    # Assert
    assert primera is None
    assert segunda == UNIQUE


def test_tc_ddl_04_combinacion_parcial_con_null_no_se_duplica(codigo_error):
    """
    Que es: prueba de UNIQUE NULLS NOT DISTINCT con una combinacion parcialmente vacia.
    Que hace: inserta un perfil (quinquenio NULL, 'Soltero', nacionalidad NULL, genero) dos veces con genero F y
              luego con genero M.
    Esperado: F entra la primera vez, F repetido falla con 23505, y M entra (es otra combinacion).
    """
    # Arrange: perfil con quinquenio y nacionalidad en NULL; solo cambia el genero
    insertar = (
        "INSERT INTO trauma_completo.dim_paciente (quinquenio, estado_civil, nacionalidad, genero) "
        "VALUES (NULL, 'Soltero', NULL, :g)"
    )

    # Act
    primera_f = codigo_error(insertar, g="F")
    segunda_f = codigo_error(insertar, g="F")
    primera_m = codigo_error(insertar, g="M")

    # Assert
    assert primera_f is None
    assert segunda_f == UNIQUE
    assert primera_m is None  # otra combinacion si entra


def test_tc_ddl_04_catalogos_con_valor_unico(codigo_error):
    """
    Que es: prueba de UNIQUE y NOT NULL en un catalogo (dim_cie_10, unico para todos los roles).
    Que hace: inserta el mismo codigo dos veces y luego una fila sin codigo.
    Esperado: el primer codigo entra; el repetido falla con 23505; la fila vacia falla con 23502 (not_null).
    """
    # Arrange: insercion de un codigo CIE-10 y una insercion sin codigo
    insertar = "INSERT INTO trauma_completo.dim_cie_10 (cie_10) VALUES (:c)"
    insertar_vacio = "INSERT INTO trauma_completo.dim_cie_10 DEFAULT VALUES"

    # Act
    primera = codigo_error(insertar, c="S06.0")
    repetida = codigo_error(insertar, c="S06.0")
    sin_codigo = codigo_error(insertar_vacio)

    # Assert
    assert primera is None
    assert repetida == UNIQUE
    assert sin_codigo == NOT_NULL


def test_tc_ddl_04_calendario_y_horario_una_fila_por_valor(codigo_error):
    """
    Que es: prueba de UNIQUE en las dimensiones de tiempo del mini.
    Que hace: inserta dos veces la misma fecha en el calendario y dos veces el mismo (hora, minuto) en el horario.
    Esperado: cada primer valor entra; cada repetido falla con 23505 (una sola fila por fecha y por minuto del dia).
    """
    # Arrange: una fecha y un minuto del dia (08:30) con todos sus atributos
    insertar_fecha = "INSERT INTO trauma_mini.dwh_dim_calendario (fecha) VALUES ('2024-01-15')"
    insertar_hora = ("INSERT INTO trauma_mini.dwh_dim_horario (hora_larga, hora, minuto, intervalo) "
                     "VALUES ('8:30:00 a. m.', 8, 30, '08:00 - 09:00')")

    # Act
    fecha_primera = codigo_error(insertar_fecha)
    fecha_repetida = codigo_error(insertar_fecha)
    hora_primera = codigo_error(insertar_hora)
    hora_repetida = codigo_error(insertar_hora)

    # Assert
    assert fecha_primera is None
    assert fecha_repetida == UNIQUE
    assert hora_primera is None
    assert hora_repetida == UNIQUE


@pytest.mark.parametrize("tabla", ["trauma_mini.dwh_dim_horario", "trauma_completo.dim_horario"])
def test_tc_ddl_04_horario_clave_hora_minuto_y_dominio(codigo_error, tabla):
    """
    Que es: prueba de la clave natural y del dominio del horario conformado (mini y completo).
    Que hace: inserta 08:30 y 08:31 (misma hora, distinto minuto) y luego una hora 24 y un minuto 60.
    Esperado: las dos primeras entran (la clave es la pareja, no la hora); hora 24 y minuto 60 fallan con
              23514 (check_violation).
    """
    # Arrange: el mismo INSERT con distintos valores; los atributos de texto no influyen en la clave
    insertar = (f"INSERT INTO {tabla} (hora_larga, hora, minuto, intervalo) "
                "VALUES ('x', :hora, :minuto, 'x')")

    # Act
    minuto_30 = codigo_error(insertar, hora=8, minuto=30)
    minuto_31 = codigo_error(insertar, hora=8, minuto=31)
    hora_24 = codigo_error(insertar, hora=24, minuto=0)
    minuto_60 = codigo_error(insertar, hora=0, minuto=60)

    # Assert
    assert minuto_30 is None
    assert minuto_31 is None
    assert hora_24 == CHECK_VIOLATION
    assert minuto_60 == CHECK_VIOLATION


def test_tc_ddl_04_festivo_del_completo_solo_si_o_no(codigo_error):
    """
    Que es: prueba del dominio de dim_tiempo.es_festivo en el modelo completo (festivos de Colombia).
    Que hace: inserta fechas con es_festivo 'SI', 'NO' y 'True' (la etiqueta del mini, no la del completo).
    Esperado: 'SI' y 'NO' entran; 'True' falla con 23514 (check_violation).
    """
    # Arrange: una fecha distinta por insercion para no chocar con el UNIQUE de fecha
    insertar = "INSERT INTO trauma_completo.dim_tiempo (fecha, es_festivo) VALUES (:f, :e)"

    # Act
    festivo = codigo_error(insertar, f="2024-01-01", e="SI")
    no_festivo = codigo_error(insertar, f="2024-01-02", e="NO")
    etiqueta_del_mini = codigo_error(insertar, f="2024-01-03", e="True")

    # Assert
    assert festivo is None
    assert no_festivo is None
    assert etiqueta_del_mini == CHECK_VIOLATION


def test_tc_ddl_04_huella_del_hecho_solo_64_hexadecimales(codigo_error):
    """
    Que es: prueba del dominio de fact_trauma.huella (carga incremental).
    Que hace: inserta hechos sin huella, con un SHA-256 en minusculas, con un texto corto y con uno en mayusculas.
    Esperado: sin huella (NULL) y con 64 hexadecimales en minuscula entran; el texto corto y el de mayusculas
              fallan con 23514 (check_violation).
    """
    # Arrange: una llave de negocio distinta por insercion para no chocar con el UNIQUE
    insertar = "INSERT INTO trauma_completo.fact_trauma (trauma_register_id, huella) VALUES (:t, :h)"

    # Act
    sin_huella = codigo_error(insertar, t="H-1", h=None)
    valida = codigo_error(insertar, t="H-2", h="a" * 64)
    corta = codigo_error(insertar, t="H-3", h="abc")
    mayusculas = codigo_error(insertar, t="H-4", h="A" * 64)

    # Assert
    assert sin_huella is None
    assert valida is None
    assert corta == CHECK_VIOLATION
    assert mayusculas == CHECK_VIOLATION


def test_tc_ddl_04_imagen_repetida_por_secuencia(conexion, codigo_error):
    """
    Que es: prueba de la clave (fact_id, secuencia) del puente de imagenes del completo (imagen realizada).
    Que hace: crea un hecho y una combinacion (TAC, Torax) sinteticos, inserta dos imagenes iguales con
              descripciones distintas (secuencias 1 y 2) y luego repite la secuencia 1.
    Esperado: las dos imagenes entran, cada una con su descripcion; la secuencia repetida falla con 23505.
    """
    # Arrange: un hecho y una combinacion tipo + region; se recuperan sus claves sustitutas generadas
    hecho = conexion.execute(text(
        "INSERT INTO trauma_completo.fact_trauma (trauma_register_id) VALUES ('I-1') RETURNING fact_id"
    )).scalar_one()
    imagen = conexion.execute(text(
        "INSERT INTO trauma_completo.dim_imagen (tipo_imagen, parte_cuerpo) VALUES ('TAC', 'Torax') "
        "RETURNING imagen_id"
    )).scalar_one()
    insertar = ("INSERT INTO trauma_completo.bridge_atencion_imagen (fact_id, secuencia, imagen_id, descripcion_imagen) "
                "VALUES (:f, :s, :i, :d)")

    # Act
    primera = codigo_error(insertar, f=hecho, s=1, i=imagen, d="texto sintetico 1")
    segunda = codigo_error(insertar, f=hecho, s=2, i=imagen, d="texto sintetico 2")
    secuencia_repetida = codigo_error(insertar, f=hecho, s=1, i=imagen, d="texto sintetico 3")

    # Assert
    assert primera is None
    assert segunda is None
    assert secuencia_repetida == UNIQUE


def test_tc_ddl_04_procedimiento_repetido_por_secuencia(conexion, codigo_error):
    """
    Que es: prueba de la clave (fact_id, secuencia) del puente de procedimientos del completo.
    Que hace: crea un hecho y un procedimiento sinteticos, inserta el mismo procedimiento con secuencias 1 y 2,
              repite la secuencia 1 y prueba una secuencia 0 y una duracion negativa.
    Esperado: las secuencias 1 y 2 entran (el mismo procedimiento puede repetirse en una atencion); la secuencia
              repetida falla con 23505; la secuencia 0 y la duracion negativa fallan con 23514 (check_violation).
    """
    # Arrange: un hecho y un procedimiento; se recuperan sus claves sustitutas generadas
    hecho = conexion.execute(text(
        "INSERT INTO trauma_completo.fact_trauma (trauma_register_id) VALUES ('P-1') RETURNING fact_id"
    )).scalar_one()
    procedimiento = conexion.execute(text(
        "INSERT INTO trauma_completo.dim_procedimiento (procedimientos) VALUES ('QUIMICA SANGUINEA') "
        "RETURNING procedimiento_id"
    )).scalar_one()
    insertar = ("INSERT INTO trauma_completo.bridge_atencion_procedimiento "
                "(fact_id, secuencia, procedimiento_id, duracion_seg) VALUES (:f, :s, :p, :d)")

    # Act
    primera = codigo_error(insertar, f=hecho, s=1, p=procedimiento, d=600)
    segunda = codigo_error(insertar, f=hecho, s=2, p=procedimiento, d=900)
    secuencia_repetida = codigo_error(insertar, f=hecho, s=1, p=procedimiento, d=600)
    secuencia_cero = codigo_error(insertar, f=hecho, s=0, p=procedimiento, d=600)
    duracion_negativa = codigo_error(insertar, f=hecho, s=3, p=procedimiento, d=-1)

    # Assert
    assert primera is None
    assert segunda is None
    assert secuencia_repetida == UNIQUE
    assert secuencia_cero == CHECK_VIOLATION
    assert duracion_negativa == CHECK_VIOLATION


def test_tc_ddl_04_complicacion_por_codigo_lugar_y_texto(conexion, codigo_error):
    """
    Que es: prueba del UNIQUE NULLS NOT DISTINCT (fact_id, cie_10_id, lugar_complicacion, texto_origen) del puente
            de complicaciones del completo (2026-10-27).
    Que hace: crea un hecho, un codigo y el miembro 'SIN CODIGO CIE-10' sinteticos; inserta la misma complicacion
              mapeada en dos lugares y la repite; luego dos textos distintos sin codigo en el mismo lugar y repite
              uno de ellos.
    Esperado: la complicacion en dos lugares entra (es multivalor); los dos textos sin codigo entran (el texto las
              distingue); cada repeticion exacta falla con 23505, tambien con texto_origen NULL (dos NULL cuentan
              como iguales).
    """
    # Arrange: un hecho, un codigo mapeado y el miembro de lo no mapeado; se recuperan sus claves generadas
    hecho = conexion.execute(text(
        "INSERT INTO trauma_completo.fact_trauma (trauma_register_id) VALUES ('K-1') RETURNING fact_id"
    )).scalar_one()
    codigo = conexion.execute(text(
        "INSERT INTO trauma_completo.dim_cie_10 (cie_10) VALUES ('J18.9') RETURNING cie_10_id"
    )).scalar_one()
    sin_codigo = conexion.execute(text(
        "INSERT INTO trauma_completo.dim_cie_10 (cie_10) VALUES ('SIN CODIGO CIE-10') RETURNING cie_10_id"
    )).scalar_one()
    insertar = ("INSERT INTO trauma_completo.bridge_atencion_complicacion "
                "(fact_id, cie_10_id, lugar_complicacion, texto_origen) VALUES (:f, :c, :l, :t)")

    # Act
    en_uci = codigo_error(insertar, f=hecho, c=codigo, l="UCI", t=None)
    en_piso = codigo_error(insertar, f=hecho, c=codigo, l="Piso", t=None)
    mapeada_repetida = codigo_error(insertar, f=hecho, c=codigo, l="UCI", t=None)
    texto_1 = codigo_error(insertar, f=hecho, c=sin_codigo, l="UCI", t="texto sintetico 1")
    texto_2 = codigo_error(insertar, f=hecho, c=sin_codigo, l="UCI", t="texto sintetico 2")
    texto_repetido = codigo_error(insertar, f=hecho, c=sin_codigo, l="UCI", t="texto sintetico 1")

    # Assert
    assert en_uci is None and en_piso is None
    assert mapeada_repetida == UNIQUE
    assert texto_1 is None and texto_2 is None
    assert texto_repetido == UNIQUE
