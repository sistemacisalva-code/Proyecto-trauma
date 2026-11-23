"""
TC-DDL-05 y TC-DDL-06: claves foraneas, ids de registro, cascada de borrado y tablas puente.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Convencion: codigo_error(sql) ejecuta la sentencia y devuelve el SQLSTATE del error
(23503 = foreign_key_violation, 23505 = unique_violation, 23502 = not_null_violation,
23514 = check_violation),
o None si la sentencia se ejecuto sin error. Todo lo que se inserta se revierte al terminar cada prueba.
"""
from sqlalchemy import text

from tests.integration_tests.ddl.constantes import CHECK_VIOLATION, FOREIGN_KEY, NOT_NULL, UNIQUE


# ---------------------------------------------------------------- TC-DDL-05
def test_tc_ddl_05_hecho_completo_con_fk_inexistente(codigo_error):
    """
    Que es: prueba de integridad referencial del hecho del modelo completo.
    Que hace: inserta hechos que apuntan a un paciente, a una fecha de alta y a una hora del alta que no
              existen (id 999999).
    Esperado: las tres inserciones fallan con 23503 (foreign_key_violation).
    """
    # Arrange: tres hechos, cada uno con una FK inexistente distinta
    con_paciente = "INSERT INTO trauma_completo.fact_trauma (trauma_register_id, paciente_id) VALUES ('T-1', 999999)"
    con_fecha = "INSERT INTO trauma_completo.fact_trauma (trauma_register_id, fecha_alta_id) VALUES ('T-2', 999999)"
    con_hora = "INSERT INTO trauma_completo.fact_trauma (trauma_register_id, hora_alta_id) VALUES ('T-3', 999999)"

    # Act
    error_paciente = codigo_error(con_paciente)
    error_fecha = codigo_error(con_fecha)
    error_hora = codigo_error(con_hora)

    # Assert
    assert error_paciente == FOREIGN_KEY
    assert error_fecha == FOREIGN_KEY
    assert error_hora == FOREIGN_KEY


def test_tc_ddl_05_id_de_registro_unico_y_obligatorio(conexion, codigo_error):
    """
    Que es: prueba de la clave de negocio trauma_register_id del modelo completo.
    Que hace: inserta '1234', otra vez '1234', '1234-1' y un registro sin id; al final cuenta los '1234%'.
    Esperado: '1234' entra; su repeticion falla con 23505; '1234-1' entra (atencion distinta del mismo
              paciente); el registro sin id falla con 23502; el conteo final es 2.
    """
    # Arrange
    insertar = "INSERT INTO trauma_completo.fact_trauma (trauma_register_id) VALUES (:r)"

    # Act
    primera = codigo_error(insertar, r="1234")
    repetida = codigo_error(insertar, r="1234")
    con_sufijo = codigo_error(insertar, r="1234-1")  # atencion distinta del mismo paciente
    sin_id = codigo_error(insertar, r=None)
    total = conexion.execute(
        text("SELECT count(*) FROM trauma_completo.fact_trauma WHERE trauma_register_id LIKE '1234%'")
    ).scalar_one()

    # Assert
    assert primera is None
    assert repetida == UNIQUE
    assert con_sufijo is None
    assert sin_id == NOT_NULL
    assert total == 2


def test_tc_ddl_05_hecho_mini_con_fk_inexistente(codigo_error):
    """
    Que es: prueba de integridad referencial del hecho del modelo mini.
    Que hace: inserta hechos que apuntan a un municipio, a una fecha de alta y a un horario de alta
              que no existen (id 999999).
    Esperado: las tres inserciones fallan con 23503 (foreign_key_violation).
    """
    # Arrange: tres hechos, cada uno con una FK a un valor inexistente
    con_municipio = "INSERT INTO trauma_mini.dwh_dim_hechos (trauma_register_record_id, municipio) VALUES ('T-1', 999999)"
    con_fecha = "INSERT INTO trauma_mini.dwh_dim_hechos (trauma_register_record_id, id_fecha_de_alta) VALUES ('T-2', 999999)"
    con_horario = "INSERT INTO trauma_mini.dwh_dim_hechos (trauma_register_record_id, id_horario_de_alta) VALUES ('T-3', 999999)"

    # Act
    error_municipio = codigo_error(con_municipio)
    error_fecha = codigo_error(con_fecha)
    error_horario = codigo_error(con_horario)

    # Assert
    assert error_municipio == FOREIGN_KEY
    assert error_fecha == FOREIGN_KEY
    assert error_horario == FOREIGN_KEY


def test_tc_ddl_05_id_de_registro_del_mini_unico(codigo_error):
    """
    Que es: prueba de la clave de negocio trauma_register_record_id del modelo mini.
    Que hace: inserta '1234', otra vez '1234' y '1234-1'.
    Esperado: '1234' entra; su repeticion falla con 23505; '1234-1' entra (es otra atencion).
    """
    # Arrange
    insertar = "INSERT INTO trauma_mini.dwh_dim_hechos (trauma_register_record_id) VALUES (:r)"

    # Act
    primera = codigo_error(insertar, r="1234")
    repetida = codigo_error(insertar, r="1234")
    con_sufijo = codigo_error(insertar, r="1234-1")

    # Assert
    assert primera is None
    assert repetida == UNIQUE
    assert con_sufijo is None


def test_tc_ddl_05_subdimension_exige_registro_y_subtipo_validos(conexion, codigo_error):
    """
    Que es: prueba de las restricciones de dwh_dim_subdimtrauma (FK al hecho, FK al catalogo y UNIQUE).
    Que hace: crea un tipo de trauma y un hecho, y luego inserta subtipos validos y no validos.
    Esperado: la primera combinacion (registro, subtipo) entra; repetirla falla con 23505; un registro
              inexistente falla con 23503; un subtipo inexistente falla con 23503.
    """
    # Arrange: un tipo de trauma y un hecho existentes
    tipo = conexion.execute(
        text("INSERT INTO trauma_mini.dwh_dim_trauma (tipo_trauma, tipo_subtrauma) VALUES ('1', '1') RETURNING key_tipotrauma")
    ).scalar_one()
    conexion.execute(text("INSERT INTO trauma_mini.dwh_dim_hechos (trauma_register_record_id) VALUES ('R-1')"))
    insertar = (
        "INSERT INTO trauma_mini.dwh_dim_subdimtrauma (trauma_register_record_id, key_tipotrauma) VALUES (:r, :k)"
    )

    # Act
    valida = codigo_error(insertar, r="R-1", k=tipo)
    repetida = codigo_error(insertar, r="R-1", k=tipo)                # mismo subtipo dos veces en un registro
    registro_inexistente = codigo_error(insertar, r="NO-EXISTE", k=tipo)
    subtipo_inexistente = codigo_error(insertar, r="R-1", k=999999)

    # Assert
    assert valida is None
    assert repetida == UNIQUE
    assert registro_inexistente == FOREIGN_KEY
    assert subtipo_inexistente == FOREIGN_KEY


# ---------------------------------------------------------------- TC-DDL-06
def test_tc_ddl_06_borrar_un_hecho_borra_sus_puentes(conexion):
    """
    Que es: prueba de ON DELETE CASCADE en las tablas puente del modelo completo.
    Que hace: crea un codigo CIE-10, un hecho y su fila en bridge_atencion_cie_10 (rol diagnostico); luego
              borra el hecho.
    Esperado: no queda ninguna fila de puente para ese hecho (conteo 0).
    """
    # Arrange: un codigo, un hecho y la fila de puente que los une
    diagnostico = conexion.execute(
        text("INSERT INTO trauma_completo.dim_cie_10 (cie_10) VALUES ('S06.0') RETURNING cie_10_id")
    ).scalar_one()
    hecho = conexion.execute(
        text("INSERT INTO trauma_completo.fact_trauma (trauma_register_id) VALUES ('C-1') RETURNING fact_id")
    ).scalar_one()
    conexion.execute(
        text("INSERT INTO trauma_completo.bridge_atencion_cie_10 (fact_id, cie_10_id, rol) VALUES (:f, :d, 'diagnostico')"),
        {"f": hecho, "d": diagnostico},
    )

    # Act: se borra el hecho y se cuentan sus filas de puente
    conexion.execute(text("DELETE FROM trauma_completo.fact_trauma WHERE fact_id = :f"), {"f": hecho})
    restantes = conexion.execute(
        text("SELECT count(*) FROM trauma_completo.bridge_atencion_cie_10 WHERE fact_id = :f"), {"f": hecho}
    ).scalar_one()

    # Assert
    assert restantes == 0


def test_tc_ddl_06_no_se_borra_un_valor_de_dimension_en_uso(conexion, codigo_error):
    """
    Que es: prueba de proteccion de los valores de dimension referenciados (sin ON DELETE CASCADE).
    Que hace: crea un diagnostico y un paciente, los usa en un hecho y en su puente, e intenta borrarlos.
    Esperado: ambos borrados fallan con 23503 (foreign_key_violation).
    """
    # Arrange: un diagnostico y un paciente, ambos en uso por un hecho (el diagnostico, ademas, por un puente)
    diagnostico = conexion.execute(
        text("INSERT INTO trauma_completo.dim_cie_10 (cie_10) VALUES ('S06.0') RETURNING cie_10_id")
    ).scalar_one()
    paciente = conexion.execute(
        text("INSERT INTO trauma_completo.dim_paciente (genero) VALUES ('F') RETURNING paciente_id")
    ).scalar_one()
    hecho = conexion.execute(
        text("INSERT INTO trauma_completo.fact_trauma (trauma_register_id, paciente_id) VALUES ('C-2', :p) RETURNING fact_id"),
        {"p": paciente},
    ).scalar_one()
    conexion.execute(
        text("INSERT INTO trauma_completo.bridge_atencion_cie_10 (fact_id, cie_10_id, rol) VALUES (:f, :d, 'diagnostico')"),
        {"f": hecho, "d": diagnostico},
    )

    # Act
    borrar_diagnostico = codigo_error(
        "DELETE FROM trauma_completo.dim_cie_10 WHERE cie_10_id = :d", d=diagnostico
    )
    borrar_paciente = codigo_error("DELETE FROM trauma_completo.dim_paciente WHERE paciente_id = :p", p=paciente)

    # Assert
    assert borrar_diagnostico == FOREIGN_KEY
    assert borrar_paciente == FOREIGN_KEY


def test_tc_ddl_06_puente_no_admite_la_misma_asociacion_dos_veces(conexion, codigo_error):
    """
    Que es: prueba del UNIQUE NULLS NOT DISTINCT de bridge_atencion_cie_10 con un codigo mapeado.
    Que hace: inserta dos veces la misma terna (hecho, codigo, rol diagnostico), sin texto_origen (NULL).
    Esperado: la primera entra (None); la segunda falla con 23505 (unique_violation): dos NULL cuentan como iguales.
    """
    # Arrange: un codigo y un hecho existentes
    diagnostico = conexion.execute(
        text("INSERT INTO trauma_completo.dim_cie_10 (cie_10) VALUES ('S06.0') RETURNING cie_10_id")
    ).scalar_one()
    hecho = conexion.execute(
        text("INSERT INTO trauma_completo.fact_trauma (trauma_register_id) VALUES ('C-3') RETURNING fact_id")
    ).scalar_one()
    insertar = "INSERT INTO trauma_completo.bridge_atencion_cie_10 (fact_id, cie_10_id, rol) VALUES (:f, :d, 'diagnostico')"

    # Act
    primera = codigo_error(insertar, f=hecho, d=diagnostico)
    repetida = codigo_error(insertar, f=hecho, d=diagnostico)

    # Assert
    assert primera is None
    assert repetida == UNIQUE


def test_tc_ddl_06_puente_cie_10_por_rol(conexion, codigo_error):
    """
    Que es: prueba del rol en el puente CIE-10 unificado.
    Que hace: inserta el mismo codigo en la misma atencion como diagnostico y como comorbilidad, y luego con
              un rol fuera de la lista ('emergencia', un papel del Excel que no entra al modelo).
    Esperado: los dos roles validos entran (el rol es parte de la clave); el rol fuera de la lista falla con
              23514 (check_violation).
    """
    # Arrange: un codigo y un hecho sinteticos
    codigo = conexion.execute(
        text("INSERT INTO trauma_completo.dim_cie_10 (cie_10) VALUES ('E11.9') RETURNING cie_10_id")
    ).scalar_one()
    hecho = conexion.execute(
        text("INSERT INTO trauma_completo.fact_trauma (trauma_register_id) VALUES ('C-4') RETURNING fact_id")
    ).scalar_one()
    insertar = "INSERT INTO trauma_completo.bridge_atencion_cie_10 (fact_id, cie_10_id, rol) VALUES (:f, :c, :r)"

    # Act
    como_diagnostico = codigo_error(insertar, f=hecho, c=codigo, r="diagnostico")
    como_comorbilidad = codigo_error(insertar, f=hecho, c=codigo, r="comorbilidad")
    rol_invalido = codigo_error(insertar, f=hecho, c=codigo, r="emergencia")

    # Assert
    assert como_diagnostico is None
    assert como_comorbilidad is None
    assert rol_invalido == CHECK_VIOLATION


def test_tc_ddl_06_cie_10_sin_codigo_conserva_cada_texto(conexion, codigo_error):
    """
    Que es: prueba de texto_origen en bridge_atencion_cie_10 (2026-10-27): los diagnosticos sin codigo no se
            pierden.
    Que hace: crea el miembro 'SIN CODIGO CIE-10' y un hecho; inserta dos textos distintos sin codigo en el mismo
              rol, repite uno, e inserta un texto igual en otro rol.
    Esperado: los dos textos distintos entran (el texto los distingue); la repeticion exacta falla con 23505; el
              mismo texto en otro rol entra (el rol es parte de la clave).
    """
    # Arrange: el miembro de lo no mapeado y un hecho sinteticos
    sin_codigo = conexion.execute(
        text("INSERT INTO trauma_completo.dim_cie_10 (cie_10) VALUES ('SIN CODIGO CIE-10') RETURNING cie_10_id")
    ).scalar_one()
    hecho = conexion.execute(
        text("INSERT INTO trauma_completo.fact_trauma (trauma_register_id) VALUES ('C-5') RETURNING fact_id")
    ).scalar_one()
    insertar = ("INSERT INTO trauma_completo.bridge_atencion_cie_10 (fact_id, cie_10_id, rol, texto_origen) "
                "VALUES (:f, :c, :r, :t)")

    # Act
    texto_1 = codigo_error(insertar, f=hecho, c=sin_codigo, r="diagnostico", t="texto sintetico 1")
    texto_2 = codigo_error(insertar, f=hecho, c=sin_codigo, r="diagnostico", t="texto sintetico 2")
    repetido = codigo_error(insertar, f=hecho, c=sin_codigo, r="diagnostico", t="texto sintetico 1")
    otro_rol = codigo_error(insertar, f=hecho, c=sin_codigo, r="comorbilidad", t="texto sintetico 1")

    # Assert
    assert texto_1 is None and texto_2 is None
    assert repetido == UNIQUE
    assert otro_rol is None


def test_tc_ddl_06_lesion_sin_mecanismo_y_repetida_entran(conexion, codigo_error):
    """
    Que es: prueba de la clave (fact_id, secuencia) de bridge_atencion_lesion (2026-10-27: todas las
            lesiones se conservan).
    Que hace: inserta una lesion sin mecanismo primario (NULL), la misma lesion otra vez con otra secuencia y la
              misma parte y tipo con mecanismo; luego repite una secuencia y prueba la secuencia 0.
    Esperado: las tres lesiones entran (la repetida es otra lesion); la secuencia repetida falla con 23505 y la
              secuencia 0 con 23514 (check_violation).
    """
    # Arrange: un hecho, una parte, un tipo y un mecanismo sinteticos
    def clave(sql):
        return conexion.execute(text(sql)).scalar_one()

    hecho = clave("INSERT INTO trauma_completo.fact_trauma (trauma_register_id) VALUES ('L-1') RETURNING fact_id")
    parte = clave("INSERT INTO trauma_completo.dim_parte_cuerpo_lesion (parte_cuerpo) VALUES ('Torax') "
                  "RETURNING parte_cuerpo_lesion_id")
    tipo = clave("INSERT INTO trauma_completo.dim_tipo_lesion (tipo_lesion) VALUES ('Contusion') RETURNING tipo_lesion_id")
    mecanismo = clave("INSERT INTO trauma_completo.dim_mecanismo_primario (mecanismo_primario) VALUES ('Contundente') "
                      "RETURNING mecanismo_primario_id")
    insertar = ("INSERT INTO trauma_completo.bridge_atencion_lesion "
                "(fact_id, secuencia, parte_cuerpo_lesion_id, mecanismo_primario_id, tipo_lesion_id) "
                "VALUES (:f, :s, :p, :m, :t)")

    # Act
    sin_mecanismo = codigo_error(insertar, f=hecho, s=1, p=parte, m=None, t=tipo)
    sin_mecanismo_repetida = codigo_error(insertar, f=hecho, s=2, p=parte, m=None, t=tipo)
    con_mecanismo = codigo_error(insertar, f=hecho, s=3, p=parte, m=mecanismo, t=tipo)
    secuencia_repetida = codigo_error(insertar, f=hecho, s=1, p=parte, m=mecanismo, t=tipo)
    secuencia_cero = codigo_error(insertar, f=hecho, s=0, p=parte, m=mecanismo, t=tipo)

    # Assert
    assert sin_mecanismo is None
    assert sin_mecanismo_repetida is None
    assert con_mecanismo is None
    assert secuencia_repetida == UNIQUE
    assert secuencia_cero == CHECK_VIOLATION


def test_tc_ddl_06_borrar_un_hecho_del_mini_borra_su_subdimension(conexion):
    """
    Que es: prueba de ON DELETE CASCADE entre el hecho del mini y dwh_dim_subdimtrauma.
    Que hace: crea un tipo de trauma, un hecho y una fila de subdimension; luego borra el hecho.
    Esperado: no queda ninguna fila de subdimension para ese registro (conteo 0).
    """
    # Arrange: un tipo de trauma, un hecho y su fila de subdimension
    tipo = conexion.execute(
        text("INSERT INTO trauma_mini.dwh_dim_trauma (tipo_trauma, tipo_subtrauma) VALUES ('1', '1') RETURNING key_tipotrauma")
    ).scalar_one()
    conexion.execute(text("INSERT INTO trauma_mini.dwh_dim_hechos (trauma_register_record_id) VALUES ('R-9')"))
    conexion.execute(
        text("INSERT INTO trauma_mini.dwh_dim_subdimtrauma (trauma_register_record_id, key_tipotrauma) VALUES ('R-9', :k)"),
        {"k": tipo},
    )

    # Act: se borra el hecho y se cuentan sus filas de subdimension
    conexion.execute(text("DELETE FROM trauma_mini.dwh_dim_hechos WHERE trauma_register_record_id = 'R-9'"))
    restantes = conexion.execute(
        text("SELECT count(*) FROM trauma_mini.dwh_dim_subdimtrauma WHERE trauma_register_record_id = 'R-9'")
    ).scalar_one()

    # Assert
    assert restantes == 0
