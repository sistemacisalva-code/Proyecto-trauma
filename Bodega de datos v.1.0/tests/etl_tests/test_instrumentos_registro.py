from types import SimpleNamespace

import pandas as pd
import pytest

from etl.transform.redcap.bloques import INSTRUMENTOS_ESPERADOS
from etl.transform.redcap.instrumentos import CATEGORICAS, TRANSFORMACIONES, _validar_contrato
from etl.transform.redcap.instrumentos import hospitalizacion, imagenes, mecanismo_de_lesion, uci


class TestInstrumentoMecanismoDeLesion:
    def test_scq_y_altura_pasan_a_float(self, reporte):
        """
        Qué es: prueba unitaria de mecanismo_de_lesion.transformar.
        Qué hace: transforma un bloque sintético con un valor de altura no numérico.
        Esperado: scq y altura_en_metros quedan como Float64; el valor no numérico pasa a nulo y se cuenta
                  como no convertible (1), sin pérdidas sin explicar.
        """
        # Arrange: tres filas, una altura ilegible (1 de 3 no convertibles, bajo el umbral de la guarda)
        df = pd.DataFrame({"record_id": ["1", "2", "3"], "scq": ["2", "3", "1"],
                           "altura_en_metros": ["1.5", "x", "1.7"]})

        # Act: transformar
        resultado = mecanismo_de_lesion.transformar(df, reporte, {})

        # Assert: tipos, nulo y auditoría
        assert str(resultado["scq"].dtype) == str(resultado["altura_en_metros"].dtype) == "Float64"
        assert resultado["altura_en_metros"].isna().tolist() == [False, True, False]
        assert reporte.auditoria[("mecanismo_de_lesion", "altura_en_metros")]["no_convertibles"] == 1
        reporte.verificar_auditoria()


class TestInstrumentoImagenes:
    def test_renombra_descripcion_y_registra_el_cambio(self, reporte):
        """
        Qué es: prueba unitaria de imagenes.transformar.
        Qué hace: transforma un bloque sintético con la columna descripcion.
        Esperado: la columna se llama descripcion_imagen, con los mismos datos, y el renombre queda registrado.
        """
        # Arrange: una imagen sintética
        df = pd.DataFrame({"record_id": ["1"], "tipo_de_imagen": ["RX"], "descripcion": ["torax"]})

        # Act: transformar
        resultado = imagenes.transformar(df, reporte, {})

        # Assert: nuevo nombre, mismo dato y trazabilidad del cambio
        assert list(resultado.columns) == ["record_id", "tipo_de_imagen", "descripcion_imagen"]
        assert resultado["descripcion_imagen"].tolist() == ["torax"]
        assert ("imagenes", "descripcion") in reporte.renombres


class TestInstrumentoHospitalizacion:
    @pytest.fixture
    def hospitalizados(self):
        """
        Bloque de hospitalización sintético de tres episodios (texto, como llega del export): uno coherente,
        uno con el alta anterior a la admisión y días negativos, y uno con días distintos a los calculados.
        """
        return pd.DataFrame({
            "record_id": ["1", "2", "3"],
            "fecha_de_admision": ["2024-01-10", "2024-02-05", "2024-03-01"],
            "fecha_y_hora_de_alta": ["2024-01-15 12:00:00", "2024-02-03 10:00:00", "2024-03-04 08:00:00"],
            "dias_de_hospitalizacion": ["5", "-2", "4"],
        })

    def test_fechas_a_datetime_y_dias_negativos_a_nulo(self, hospitalizados, reporte):
        """
        Qué es: prueba unitaria de hospitalizacion.transformar (tipado).
        Qué hace: transforma el bloque sintético.
        Esperado: las dos fechas son datetime, dias_de_hospitalizacion es Int64 y el -2 se invalida (no se aplica
                  valor absoluto); la auditoría cuenta 1 fuera de rango y conserva todo.
        """
        # Arrange: bloque del fixture

        # Act: transformar
        resultado = hospitalizacion.transformar(hospitalizados, reporte, {})

        # Assert: tipos, negativo invalidado y auditoría
        assert pd.api.types.is_datetime64_any_dtype(resultado["fecha_de_admision"])
        assert pd.api.types.is_datetime64_any_dtype(resultado["fecha_y_hora_de_alta"])
        assert str(resultado["dias_de_hospitalizacion"].dtype) == "Int64"
        assert resultado["dias_de_hospitalizacion"].isna().tolist() == [False, True, False]
        assert reporte.auditoria[("hospitalizacion", "dias_de_hospitalizacion")]["fuera_de_rango"] == 1
        reporte.verificar_auditoria()

    def test_reglas_de_consistencia_se_reportan_sin_modificar(self, hospitalizados, reporte, regla):
        """
        Qué es: prueba unitaria de las reglas de hospitalizacion.
        Qué hace: transforma el bloque y consulta las dos reglas.
        Esperado: el alta anterior a la admisión incumple en 1 de 3 filas (por día); los días distintos de los
                  calculados incumplen en 1 de 2 evaluables (el negativo ya es nulo); las fechas no se alteran.
        """
        # Arrange: bloque del fixture

        # Act: transformar
        resultado = hospitalizacion.transformar(hospitalizados, reporte, {})

        # Assert: conteos de las reglas y fechas intactas
        assert regla("hospitalizacion", "alta anterior a fecha_de_admision") == (3, 1)
        assert regla("hospitalizacion", "distinto de los dias calculados") == (2, 1)
        assert resultado.loc[1, "fecha_y_hora_de_alta"] == pd.Timestamp("2024-02-03 10:00:00")


class TestInstrumentoUci:
    @pytest.fixture
    def ventilador(self):
        """
        Bloque de UCI sintético de tres filas (texto): una coherente, una con el término anterior al inicio
        y una con solo la fecha de inicio.
        """
        return pd.DataFrame({
            "record_id": ["1", "2", "3"],
            "fecha_y_hora_de_inicio_del_ventilador": ["2024-01-10 12:00", "2024-01-10 12:00", "2024-01-10 12:00"],
            "fecha_y_hora_de_termino_del_ventilador": ["2024-01-12 12:00", "2024-01-09 12:00", None],
            "dias_usados": ["2", "0", "1"],
        })

    def test_tipos_y_auditoria(self, ventilador, reporte):
        """
        Qué es: prueba unitaria de uci.transformar (tipado).
        Qué hace: transforma el bloque sintético.
        Esperado: las fechas son datetime, dias_usados se renombra a dias_usados_uci y es Int64 y no hay
                  pérdidas sin explicar.
        """
        # Arrange: bloque del fixture

        # Act: transformar
        resultado = uci.transformar(ventilador, reporte, {})

        # Assert: tipos y auditoría
        assert pd.api.types.is_datetime64_any_dtype(resultado["fecha_y_hora_de_inicio_del_ventilador"])
        assert pd.api.types.is_datetime64_any_dtype(resultado["fecha_y_hora_de_termino_del_ventilador"])
        assert "dias_usados" not in resultado.columns
        assert str(resultado["dias_usados_uci"].dtype) == "Int64"
        reporte.verificar_auditoria()

    def test_reglas_de_consistencia(self, ventilador, reporte, regla):
        """
        Qué es: prueba unitaria de las tres reglas de uci.
        Qué hace: transforma el bloque y consulta las reglas.
        Esperado: término anterior al inicio incumple en 1 de 2 evaluables; una sola fecha presente incumple en
                  1 de 3; y dias_usados_uci distinto de los días completos calculados incumple en 1 de 2 evaluables.
        """
        # Arrange: bloque del fixture

        # Act: transformar
        uci.transformar(ventilador, reporte, {})

        # Assert: conteos por regla
        assert regla("uci", "anterior al inicio") == (2, 1)
        assert regla("uci", "solo una de las dos fechas") == (3, 1)
        assert regla("uci", "distinto de los dias completos") == (2, 1)


class TestRegistroDeInstrumentos:
    def _modulo(self, **cambios):
        """Módulo falso (solo para probar el contrato) con los atributos requeridos y los cambios indicados."""
        atributos = {"__name__": "modulo_falso", "NOMBRE": "uci", "CATEGORICAS": (),
                     "transformar": lambda df, reporte, bloques: df}
        atributos.update(cambios)
        return SimpleNamespace(**atributos)

    def test_modulo_valido_no_falla(self):
        """
        Qué es: prueba unitaria de _validar_contrato (caso normal).
        Qué hace: valida un módulo falso que cumple el contrato.
        Esperado: no lanza ninguna excepción.
        """
        # Arrange: módulo falso completo
        modulo = self._modulo()

        # Act + Assert: no lanza
        _validar_contrato([modulo])

    def test_atributo_faltante_falla(self):
        """
        Qué es: prueba unitaria de _validar_contrato sin un atributo requerido.
        Qué hace: valida un módulo al que le falta transformar.
        Esperado: AttributeError que explica que no cumple el contrato.
        """
        # Arrange: módulo sin transformar
        modulo = SimpleNamespace(__name__="modulo_falso", NOMBRE="uci", CATEGORICAS=())

        # Act + Assert: se detiene al importar, no al transformar
        with pytest.raises(AttributeError, match="no cumple el contrato"):
            _validar_contrato([modulo])

    def test_transformar_que_no_es_funcion_falla(self):
        """
        Qué es: prueba unitaria de _validar_contrato con transformar no invocable.
        Qué hace: valida un módulo cuyo transformar es un texto.
        Esperado: TypeError que menciona transformar.
        """
        # Arrange: transformar no invocable
        modulo = self._modulo(transformar="no es una función")

        # Act + Assert: se detiene
        with pytest.raises(TypeError, match="transformar"):
            _validar_contrato([modulo])

    def test_instrumento_registrado_dos_veces_falla(self):
        """
        Qué es: prueba unitaria de _validar_contrato con nombres repetidos.
        Qué hace: valida dos módulos con el mismo NOMBRE.
        Esperado: ValueError que dice "más de una vez" (el segundo sobrescribiría al primero sin avisar).
        """
        # Arrange: dos módulos para el mismo instrumento
        modulos = [self._modulo(), self._modulo()]

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="más de una vez"):
            _validar_contrato(modulos)

    def test_nombre_desconocido_falla(self):
        """
        Qué es: prueba unitaria de _validar_contrato con un NOMBRE que no es un instrumento esperado.
        Qué hace: valida un módulo cuyo NOMBRE no está en INSTRUMENTOS_ESPERADOS.
        Esperado: ValueError que dice "no reconocido" (un nombre mal escrito dejaría al módulo sin ejecutarse).
        """
        # Arrange: nombre mal escrito
        modulo = self._modulo(NOMBRE="uci_mal_escrito")

        # Act + Assert: se detiene
        with pytest.raises(ValueError, match="no reconocido"):
            _validar_contrato([modulo])

    def test_solo_examen_fisico_queda_sin_modulo(self):
        """
        Qué es: prueba del registro real de instrumentos (decisión 2.27).
        Qué hace: compara los instrumentos esperados con los que tienen transformación.
        Esperado: hay 14 con módulo (motivo_de_consulta por las sustancias; comorbilidades, complicaciones y
                  cie_10_diagnosticos por la etiqueta CIE-10 canónica), sus categóricas están registradas, y solo examen_fisico no tiene.
        """
        # Arrange: registro real importado

        # Act: instrumentos esperados que no tienen transformación
        sin_modulo = set(INSTRUMENTOS_ESPERADOS) - set(TRANSFORMACIONES)

        # Assert: solo examen_fisico queda sin módulo
        assert len(TRANSFORMACIONES) == 14
        assert set(CATEGORICAS) == set(TRANSFORMACIONES)
        assert sin_modulo == {"examen_fisico"}
