import pandas as pd
import pytest

from etl.transform.common.quality import CARDINALIDAD_MAXIMA


class TestReporteCalidadAuditoria:
    def test_registra_conteos_de_conservacion(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.registrar_auditoria (caso normal).
        Qué hace: audita una conversión sintética de texto a Int64 sin pérdidas.
        Esperado: guarda no nulos antes y después (2 y 2), el tipo final "Int64" y conserva = True.
        """
        # Arrange: una columna de texto con 2 valores y su versión convertida
        original = pd.Series(["1", "2", None])
        resultado = pd.Series([1, 2, pd.NA], dtype="Int64")

        # Act: registrar la auditoría
        reporte.registrar_auditoria("demo", "edad", original, resultado)

        # Assert: los conteos permiten demostrar que la transformación no perdió información
        fila = reporte.auditoria[("demo", "edad")]
        assert (fila["no_nulos_antes"], fila["no_nulos_despues"]) == (2, 2)
        assert fila["tipo_despues"] == "Int64"
        assert fila["conserva"] is True

    def test_perdida_sin_explicar_marca_no_conserva(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.registrar_auditoria (pérdida inexplicada).
        Qué hace: audita una columna que pasa de 3 a 2 valores sin declarar causa.
        Esperado: diferencia_sin_explicar = 1 y conserva = False.
        """
        # Arrange: se pierde un valor y no se informa como no convertible ni fuera de rango
        original = pd.Series([1, 2, 3])
        resultado = pd.Series([1, 2, pd.NA], dtype="Int64")

        # Act: registrar la auditoría sin explicación
        reporte.registrar_auditoria("demo", "x", original, resultado)

        # Assert: cualquier pérdida no declarada debe quedar visible
        fila = reporte.auditoria[("demo", "x")]
        assert fila["diferencia_sin_explicar"] == 1
        assert fila["conserva"] is False

    def test_perdidas_explicadas_conservan(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.registrar_auditoria (pérdidas declaradas).
        Qué hace: audita una columna que pasa de 4 a 2 valores, declarando 1 no convertible y 1 fuera de rango.
        Esperado: diferencia_sin_explicar = 0 y conserva = True.
        """
        # Arrange: 4 valores antes, 2 después; las 2 pérdidas se declaran por causa
        original = pd.Series([1, 2, 3, 4])
        resultado = pd.Series([1, 2, pd.NA, pd.NA], dtype="Int64")

        # Act: registrar con las causas de la pérdida
        reporte.registrar_auditoria("demo", "x", original, resultado, no_convertibles=1, fuera_de_rango=1)

        # Assert: solo la pérdida explicada por conversión o dominio es aceptable
        fila = reporte.auditoria[("demo", "x")]
        assert fila["diferencia_sin_explicar"] == 0
        assert fila["conserva"] is True

    def test_auditar_dos_veces_la_misma_columna_lanza_valueerror(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.registrar_auditoria (control de duplicidad).
        Qué hace: registra dos veces la misma variable del mismo bloque.
        Esperado: la segunda llamada lanza ValueError (una columna se transformó dos veces).
        """
        # Arrange: una primera auditoría ya registrada
        serie = pd.Series([1, 2])
        reporte.registrar_auditoria("demo", "x", serie, serie)

        # Act + Assert: repetirla indica un error de lógica en un reporte nuevo por corrida
        with pytest.raises(ValueError):
            reporte.registrar_auditoria("demo", "x", serie, serie)

    def test_registra_el_desglose_del_rango(self, reporte):
        """
        Qué es: prueba unitaria del desglose de fuera_de_rango en ReporteCalidad.registrar_auditoria.
        Qué hace: audita una columna que pasa de 4 a 1 valores, con 3 fuera de rango (1 por debajo y 2 por encima).
        Esperado: bajo_minimo = 1, sobre_maximo = 2 y la auditoría conserva = True.
        """
        # Arrange: tres valores invalidados por el rango
        original = pd.Series([1, 2, 3, 4])
        resultado = pd.Series([1, pd.NA, pd.NA, pd.NA], dtype="Int64")

        # Act: registrar con el desglose
        reporte.registrar_auditoria("demo", "x", original, resultado, fuera_de_rango=3,
                                    bajo_minimo=1, sobre_maximo=2)

        # Assert: el desglose queda guardado y la regla de conservación se cumple
        fila = reporte.auditoria[("demo", "x")]
        assert (fila["bajo_minimo"], fila["sobre_maximo"], fila["conserva"]) == (1, 2, True)

    def test_desglose_que_no_suma_el_total_falla(self, reporte):
        """
        Qué es: prueba unitaria de la coherencia del desglose del rango.
        Qué hace: registra bajo_minimo = 1 y sobre_maximo = 1 con fuera_de_rango = 3.
        Esperado: ValueError (el desglose debe sumar fuera_de_rango) y la variable no queda registrada.
        """
        # Arrange: desglose incoherente con el total
        serie = pd.Series([1, 2])

        # Act + Assert: se detiene en lugar de guardar un reporte contradictorio
        with pytest.raises(ValueError, match="fuera_de_rango"):
            reporte.registrar_auditoria("demo", "x", serie, serie, fuera_de_rango=3, bajo_minimo=1, sobre_maximo=1)
        assert ("demo", "x") not in reporte.auditoria

    def test_verificar_auditoria_detiene_con_perdida(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.verificar_auditoria (caso defectuoso).
        Qué hace: verifica un reporte que contiene una variable con pérdida sin explicar.
        Esperado: lanza ValueError y el mensaje nombra la columna afectada.
        """
        # Arrange: una variable que pierde un valor sin causa declarada
        reporte.registrar_auditoria("demo", "columna_con_perdida", pd.Series([1, 2]),
                                    pd.Series([1, pd.NA], dtype="Int64"))

        # Act + Assert: el pipeline no debe continuar con datos perdidos sin explicación
        with pytest.raises(ValueError, match="columna_con_perdida"):
            reporte.verificar_auditoria()

    def test_verificar_auditoria_devuelve_tabla_si_todo_conserva(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.verificar_auditoria (control positivo).
        Qué hace: verifica un reporte con una sola variable que conserva todos sus datos.
        Esperado: devuelve un DataFrame de una fila con la columna auditada.
        """
        # Arrange: una variable sin pérdidas
        serie = pd.Series([1, 2])
        reporte.registrar_auditoria("demo", "x", serie, serie)

        # Act: verificar
        tabla = reporte.verificar_auditoria()

        # Assert: la tabla es la evidencia reutilizable para el informe de calidad
        assert len(tabla) == 1
        assert tabla.loc[0, "columna"] == "x"

    def test_verificar_auditoria_sin_registros_devuelve_tabla_vacia(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.verificar_auditoria (reporte sin auditorías).
        Qué hace: verifica un reporte recién creado.
        Esperado: no falla y devuelve una tabla vacía.
        """
        # Arrange: reporte nuevo, sin variables auditadas

        # Act: verificar
        tabla = reporte.verificar_auditoria()

        # Assert: no hay nada que objetar
        assert tabla.empty


class TestReporteCalidadReglasYTrazabilidad:
    def test_reportar_regla_cuenta_solo_filas_evaluables(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.reportar_regla.
        Qué hace: reporta una regla con 3 filas evaluables, donde una incumple, otra incumple pero no
                  es evaluable y otra tiene resultado nulo.
        Esperado: filas_evaluables = 3 y filas_que_incumplen = 1.
        """
        # Arrange: la fila 3 incumple pero no es evaluable; la fila 4 no tiene resultado (nulo)
        evaluables = pd.Series([True, True, False, True])
        incumplen = pd.Series([True, False, True, None], dtype="boolean")

        # Act: reportar la regla
        reporte.reportar_regla("demo", "regla de prueba", evaluables, incumplen)

        # Assert: solo cuentan los incumplimientos de filas evaluables; el nulo no se cuenta como violación
        fila = reporte.reglas[("demo", "regla de prueba")]
        assert fila["filas_evaluables"] == 3
        assert fila["filas_que_incumplen"] == 1

    def test_registrar_correccion_guarda_solo_conteos(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.registrar_correccion y de la política de privacidad.
        Qué hace: registra una corrección con 4 filas afectadas.
        Esperado: la entrada contiene únicamente bloque, columna, regla, acción y conteo (sin valores).
        """
        # Arrange: una corrección sintética

        # Act: registrar
        reporte.registrar_correccion("demo", "fecha", "regla de prueba", 4, "invalidado (NA)")

        # Assert: el reporte solo guarda agregados, nunca valores de pacientes
        fila = reporte.correcciones[("demo", "fecha", "regla de prueba")]
        assert set(fila) == {"bloque", "columna", "regla", "accion", "filas_afectadas"}
        assert fila["filas_afectadas"] == 4

    def test_registrar_equivalencia_solo_guarda_columnas_que_cambiaron(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.registrar_equivalencia.
        Qué hace: registra una equivalencia con una columna que no cambia y una que sí.
        Esperado: solo la columna renombrada queda en el registro, bajo el bloque "global".
        """
        # Arrange: "record_id" no cambia; "Dirección" pasa a "direccion"
        equivalencia = {"record_id": "record_id", "Dirección": "direccion"}

        # Act: registrar
        reporte.registrar_equivalencia(equivalencia)

        # Assert: el registro de renombres no se llena con identidades
        assert list(reporte.renombres) == [("global", "Dirección")]

    def test_registrar_consolidacion_acumula_resumenes(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.registrar_consolidacion y tabla().
        Qué hace: registra dos resúmenes de consolidación y pide la tabla "consolidacion".
        Esperado: la tabla tiene 2 filas con los conteos registrados.
        """
        # Arrange: dos resúmenes sintéticos (solo conteos)
        reporte.registrar_consolidacion({"filas_totales": 10})
        reporte.registrar_consolidacion({"filas_totales": 12})

        # Act: obtener la tabla
        tabla = reporte.tabla("consolidacion")

        # Assert: cada corrida deja su resumen
        assert tabla["filas_totales"].tolist() == [10, 12]

    def test_registrar_descartes_acumula_conteos_por_instrumento(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.registrar_descartes y tabla().
        Qué hace: registra los descartes de dos instrumentos sintéticos y pide la tabla "descartes".
        Esperado: la tabla tiene una fila por instrumento y marcador, con las columnas instrumento,
                  marcador y filas_descartadas; sin valores de pacientes.
        """
        # Arrange: conteos sintéticos
        reporte.registrar_descartes([{"instrumento": "uci", "marcador": "Complete", "filas_descartadas": 3}])
        reporte.registrar_descartes([{"instrumento": "imagenes", "marcador": "(vacío)", "filas_descartadas": 8}])

        # Act: obtener la tabla
        tabla = reporte.tabla("descartes")

        # Assert: las dos llamadas se acumulan y la tabla tiene el esquema esperado
        assert list(tabla.columns) == ["instrumento", "marcador", "filas_descartadas"]
        assert tabla["filas_descartadas"].tolist() == [3, 8]


class TestReporteCalidadPerfilado:
    def test_perfil_cuenta_filas_nulos_y_distintos(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.perfilar (conteos por columna).
        Qué hace: perfila una columna numérica de 4 filas con 1 nulo y 2 valores distintos.
        Esperado: n_filas = 4, n_nulos = 1, n_unicos = 2 y etapa "antes".
        """
        # Arrange: columna sintética con un repetido y un nulo
        df = pd.DataFrame({"a": [1.0, 2.0, 2.0, None]})

        # Act: perfilar
        reporte.perfilar(df, "demo", "antes")

        # Assert: el perfil resume el estado de la columna en esa etapa
        fila = reporte.perfiles[0]
        assert (fila["n_filas"], fila["n_nulos"], fila["n_unicos"], fila["etapa"]) == (4, 1, 2, "antes")

    def test_valores_unicos_solo_para_categoricas_declaradas(self, reporte):
        """
        Qué es: prueba unitaria de la política de privacidad de ReporteCalidad.perfilar.
        Qué hace: perfila dos columnas y declara solo una como categórica.
        Esperado: la categórica lista sus valores únicos ordenados; la otra solo deja el conteo.
        """
        # Arrange: "sexo" es categórica declarada; "texto" no
        df = pd.DataFrame({"sexo": ["M", "F", "M"], "texto": ["x", "y", "z"]})

        # Act: perfilar declarando categoricas
        reporte.perfilar(df, "demo", "antes", categoricas=("sexo",))

        # Assert: el contenido de una columna no declarada nunca se lista
        perfil = {f["columna"]: f for f in reporte.perfiles}
        assert perfil["sexo"]["valores_unicos"] == ["F", "M"]
        assert perfil["texto"]["valores_unicos"] is None
        assert perfil["texto"]["n_unicos"] == 3

    def test_categorica_sobre_el_umbral_no_lista_valores(self, reporte):
        """
        Qué es: prueba unitaria del límite de cardinalidad de ReporteCalidad.perfilar.
        Qué hace: perfila una columna categórica con CARDINALIDAD_MAXIMA + 1 valores distintos.
        Esperado: no se listan los valores y n_unicos refleja el conteo real.
        """
        # Arrange: una categórica con un valor más que el tope permitido
        df = pd.DataFrame({"cat": [str(i) for i in range(CARDINALIDAD_MAXIMA + 1)]})

        # Act: perfilar
        reporte.perfilar(df, "demo", "antes", categoricas=("cat",))

        # Assert: una cardinalidad alta se trata como texto potencialmente sensible
        fila = reporte.perfiles[0]
        assert fila["valores_unicos"] is None
        assert fila["n_unicos"] == CARDINALIDAD_MAXIMA + 1

    def test_etapa_invalida_lanza_valueerror(self, reporte):
        """
        Qué es: prueba unitaria de validación de entrada de ReporteCalidad.perfilar.
        Qué hace: perfila con una etapa distinta de "antes" y "despues".
        Esperado: lanza ValueError.
        """
        # Arrange: un DataFrame mínimo

        # Act + Assert: las etapas permitidas son un contrato del reporte
        with pytest.raises(ValueError):
            reporte.perfilar(pd.DataFrame({"a": [1]}), "demo", "durante")

    def test_perfil_antes_y_despues_registra_el_cambio_de_tipo(self, reporte):
        """
        Qué es: prueba unitaria del perfilado antes y después de transformar.
        Qué hace: perfila una columna de texto, la convierte a numérica y la perfila de nuevo.
        Esperado: hay una fila por etapa y los tipos registrados difieren.
        """
        # Arrange: columna de texto numérico
        df = pd.DataFrame({"x": ["1", "2"]})

        # Act: perfilar antes, convertir y perfilar después
        reporte.perfilar(df, "demo", "antes")
        df["x"] = pd.to_numeric(df["x"])
        reporte.perfilar(df, "demo", "despues")

        # Assert: el contraste de tipos entre etapas es lo que documenta la transformación
        antes, despues = reporte.perfiles
        assert (antes["etapa"], despues["etapa"]) == ("antes", "despues")
        assert antes["tipo"] != despues["tipo"]


class TestReporteCalidadDuplicados:
    def test_marca_todas_las_filas_del_grupo_repetido(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.marcar_duplicados (caso con duplicados).
        Qué hace: marca duplicados por una columna donde dos de cuatro filas repiten el valor.
        Esperado: se registran las 2 filas del grupo (con n_en_grupo = 2) y el resumen indica
                  1 combinación repetida y es_unica = False.
        """
        # Arrange: los registros "1" y "2" comparten el mismo documento sintético
        df = pd.DataFrame({"record_id": ["1", "2", "3", "4"], "doc": ["A", "A", "B", "C"]})

        # Act: marcar
        reporte.marcar_duplicados(df, "global", "regla_negocio", ["doc"])

        # Assert: se marca todo el grupo (keep=False), no solo la repetición posterior
        marcados = reporte.tabla("duplicados")
        resumen = reporte.resumen_duplicados[-1]
        assert sorted(marcados["record_id"]) == ["1", "2"]
        assert (marcados["n_en_grupo"] == 2).all()
        assert (resumen["filas_involucradas"], resumen["combinaciones_repetidas"], resumen["es_unica"]) == (2, 1, False)

    def test_clave_unica_no_registra_duplicados(self, reporte):
        """
        Qué es: prueba unitaria de ReporteCalidad.marcar_duplicados (control positivo).
        Qué hace: marca duplicados sobre una columna sin valores repetidos.
        Esperado: la tabla de duplicados queda vacía y el resumen indica es_unica = True.
        """
        # Arrange: valores todos distintos
        df = pd.DataFrame({"record_id": ["1", "2"], "doc": ["A", "B"]})

        # Act: marcar
        reporte.marcar_duplicados(df, "global", "regla_negocio", ["doc"])

        # Assert: sin repetidos no se registra ninguna fila
        assert reporte.tabla("duplicados").empty
        assert reporte.resumen_duplicados[-1]["es_unica"] is True

    def test_ignorar_nulos_excluye_filas_con_nulo_en_la_clave(self, reporte):
        """
        Qué es: prueba unitaria del parámetro ignorar_nulos=True de marcar_duplicados.
        Qué hace: marca duplicados sobre una columna con dos nulos y dos valores distintos.
        Esperado: solo 2 filas son evaluables y no hay duplicados (los nulos no cuentan como repetidos).
        """
        # Arrange: dos filas con nulo en la clave (nulo estructural, no un dato repetido)
        df = pd.DataFrame({"record_id": ["1", "2", "3", "4"], "doc": [None, None, "A", "B"]})

        # Act: marcar con el valor por defecto (ignorar_nulos=True)
        reporte.marcar_duplicados(df, "global", "regla_negocio", ["doc"])

        # Assert: evita el falso positivo de tratar vacíos estructurales como duplicados
        resumen = reporte.resumen_duplicados[-1]
        assert (resumen["filas_evaluables"], resumen["filas_involucradas"]) == (2, 0)

    def test_ignorar_nulos_falso_trata_los_nulos_como_iguales(self, reporte):
        """
        Qué es: prueba unitaria del parámetro ignorar_nulos=False de marcar_duplicados.
        Qué hace: marca duplicados sobre la misma columna con dos nulos, sin ignorarlos.
        Esperado: las 2 filas con nulo se marcan como un grupo repetido.
        """
        # Arrange: mismos datos del caso anterior
        df = pd.DataFrame({"record_id": ["1", "2", "3", "4"], "doc": [None, None, "A", "B"]})

        # Act: marcar sin ignorar nulos
        reporte.marcar_duplicados(df, "global", "fila_exacta", ["doc"], ignorar_nulos=False)

        # Assert: necesario para claves donde el nulo es parte legítima de la clave
        assert reporte.resumen_duplicados[-1]["filas_involucradas"] == 2

    def test_clave_estructural_con_instancias_nulas(self, reporte):
        """
        Qué es: prueba unitaria de marcar_duplicados con la clave estructural de REDCap.
        Qué hace: marca la clave (record_id, instrumento, instancia) con instrumento e instancia nulos,
                  una vez con ignorar_nulos=True y otra con False.
        Esperado: con True no queda ninguna fila evaluable; con False se detecta el registro "1" repetido.
        """
        # Arrange: filas no repetibles (instrumento e instancia nulos por estructura); "1" aparece dos veces
        df = pd.DataFrame({
            "record_id": ["1", "1", "2"],
            "redcap_repeat_instrument": [None, None, None],
            "redcap_repeat_instance": [None, None, None],
        })
        clave = ["record_id", "redcap_repeat_instrument", "redcap_repeat_instance"]

        # Act: marcar con ambos valores de ignorar_nulos
        reporte.marcar_duplicados(df, "global", "clave_estructural", clave, ignorar_nulos=True)
        reporte.marcar_duplicados(df, "global", "clave_estructural", clave, ignorar_nulos=False)

        # Assert: por eso el nivel estructural debe usar ignorar_nulos=False
        con_true, con_false = reporte.resumen_duplicados
        assert con_true["filas_evaluables"] == 0
        assert con_false["filas_involucradas"] == 2

    def test_no_guarda_los_valores_de_la_clave(self, reporte):
        """
        Qué es: prueba unitaria de la política de privacidad de marcar_duplicados.
        Qué hace: marca duplicados por una columna de documento sintético y lista las columnas guardadas.
        Esperado: la tabla de duplicados solo tiene bloque, nivel, record_id, grupo y n_en_grupo.
        """
        # Arrange: un documento sintético repetido
        df = pd.DataFrame({"record_id": ["1", "2"], "documento": ["DOC-X", "DOC-X"]})

        # Act: marcar
        reporte.marcar_duplicados(df, "global", "regla_negocio", ["documento"])

        # Assert: el valor de la clave (que podría ser un identificador) nunca llega al reporte
        columnas = set(reporte.tabla("duplicados").columns)
        assert columnas == {"bloque", "nivel", "record_id", "grupo", "n_en_grupo"}

    def test_no_modifica_el_dataframe(self, reporte):
        """
        Qué es: prueba unitaria del contrato "solo se marca, no se elimina" de marcar_duplicados.
        Qué hace: marca duplicados y compara el DataFrame con una copia hecha antes.
        Esperado: el DataFrame queda idéntico.
        """
        # Arrange: datos con un duplicado y una copia de referencia
        df = pd.DataFrame({"record_id": ["1", "2", "3"], "doc": ["A", "A", "B"]})
        copia = df.copy()

        # Act: marcar
        reporte.marcar_duplicados(df, "global", "regla_negocio", ["doc"])

        # Assert: qué hacer con los duplicados es una decisión posterior, no de esta función
        pd.testing.assert_frame_equal(df, copia)

    def test_columna_ausente_lanza_keyerror(self, reporte):
        """
        Qué es: prueba unitaria de validación de entrada de marcar_duplicados.
        Qué hace: marca duplicados por una columna que no existe.
        Esperado: lanza KeyError.
        """
        # Arrange: DataFrame sin la columna pedida
        df = pd.DataFrame({"record_id": ["1"]})

        # Act + Assert: una clave inexistente debe detener el proceso, no producir un reporte vacío engañoso
        with pytest.raises(KeyError):
            reporte.marcar_duplicados(df, "global", "regla_negocio", ["no_existe"])


class TestReporteCalidadDetalleFilas:
    def test_regla_con_llaves_guarda_las_llaves_de_las_filas_que_incumplen(self, reporte):
        """
        Qué es: prueba unitaria de `reportar_regla` con llaves (tabla detalle_filas).
        Qué hace: reporta una regla sintética sobre 5 filas de 4 registros (A repetido), una no evaluable.
        Esperado: detalle_filas guarda una fila por llave que incumple (A con 2 filas y C con 1), tipo "incumple", sin
                  columna y sin la fila no evaluable; los conteos de la regla no cambian.
        """
        # Arrange: la fila 4 (registro D) incumple pero no es evaluable
        llaves = pd.Series(["A", "A", "B", "C", "D"])
        evaluables = pd.Series([True, True, True, True, False])
        incumplen = pd.Series([True, True, False, True, True])

        # Act
        reporte.reportar_regla("demo", "regla de prueba", evaluables, incumplen, llaves)

        # Assert
        detalle = reporte.tabla("detalle_filas")
        assert detalle[["llave", "filas"]].values.tolist() == [["A", 2], ["C", 1]]
        assert set(detalle["tipo"]) == {"incumple"} and set(detalle["bloque"]) == {"demo"}
        assert reporte.reglas[("demo", "regla de prueba")]["filas_que_incumplen"] == 3

    def test_sin_llaves_no_se_guarda_detalle(self, reporte):
        """
        Qué es: prueba unitaria de la compatibilidad de `reportar_regla` sin llaves.
        Qué hace: reporta una regla que incumple sin pasar las llaves.
        Esperado: la regla se cuenta y detalle_filas queda vacío.
        """
        # Arrange + Act
        reporte.reportar_regla("demo", "regla de prueba", pd.Series([True, True]), pd.Series([True, False]))

        # Assert
        assert reporte.tabla("detalle_filas").empty
        assert reporte.reglas[("demo", "regla de prueba")]["filas_que_incumplen"] == 1

    def test_llaves_desalineadas_se_rechazan(self, reporte):
        """
        Qué es: prueba unitaria de la protección contra llaves de otras filas.
        Qué hace: pasa llaves cuyo índice no corresponde al de las filas evaluadas.
        Esperado: ValueError; es preferible detenerse a asignar la llave de otro registro.
        """
        # Arrange: la máscara tiene índice 10 y 11; las llaves, 0 y 1
        evaluables = pd.Series([True, True], index=[10, 11])
        llaves = pd.Series(["A", "B"], index=[0, 1])

        # Act + Assert
        with pytest.raises(ValueError, match="no están alineadas"):
            reporte.reportar_regla("demo", "regla de prueba", evaluables, evaluables, llaves)

    def test_correccion_con_afectadas_guarda_las_llaves_y_la_columna(self, reporte):
        """
        Qué es: prueba unitaria de `registrar_correccion` con llaves y filas afectadas.
        Qué hace: registra una invalidación sintética de la columna "fecha" que afecta a una de tres filas.
        Esperado: detalle_filas guarda esa llave con tipo "corregida" y la columna "fecha"; la tabla de correcciones
                  sigue con solo conteos.
        """
        # Arrange
        llaves = pd.Series(["A", "B", "C"])
        afectadas = pd.Series([False, True, False])

        # Act
        reporte.registrar_correccion("demo", "fecha", "regla de prueba", 1, "invalidado (NA)", llaves, afectadas)

        # Assert
        detalle = reporte.tabla("detalle_filas").iloc[0]
        assert (detalle["llave"], detalle["tipo"], detalle["columna"]) == ("B", "corregida", "fecha")
        assert set(reporte.tabla("correcciones").columns) == {"bloque", "columna", "regla", "accion", "filas_afectadas"}

    def test_llaves_del_dataframe_usa_la_columna_de_cada_fuente(self, reporte):
        """
        Qué es: prueba unitaria de `ReporteCalidad.llaves` (qué columna identifica el registro).
        Qué hace: pide las llaves de tablas con la columna de REDCap, la del Excel y ninguna.
        Esperado: devuelve la columna que corresponda y None si la tabla no tiene ninguna de ellas.
        """
        # Arrange + Act + Assert
        assert reporte.llaves(pd.DataFrame({"record_id": ["1"]})).tolist() == ["1"]
        assert reporte.llaves(pd.DataFrame({"traumaregisterrecordid": ["9"]})).tolist() == ["9"]
        assert reporte.llaves(pd.DataFrame({"otra": [1]})) is None
