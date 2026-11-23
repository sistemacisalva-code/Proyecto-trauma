import pandas as pd
import pytest

from etl.transform.factory import TransformerFactory
from etl.transform.redcap.bloques import INSTRUMENTOS_ESPERADOS
from etl.transform.redcap_transformer import REDCapTransformer

CLAVE_SINTETICA = "clave-sintetica-de-prueba-0123456789"
PARTICION_ANTIGUA = "2026-10-01T100000"
PARTICION_NUEVA = "2026-10-02T100000"

SIGNOS = {
    "fecha_y_hora_de_signos_vitales": "2024-01-10 08:45", "frecuencia_cardiaca": "88",
    "presion_arterial_sistolica": "120", "presion_arterial_diastolica": "80",
    "frecuencia_respiratoria": "18", "saturacion_de_oxigeno": "97", "temperatura": "36.5",
    "peso": "70", "altura": "1.7", "gcs_total": "15", "gcs_ocular": "4", "gcs_verbal": "5",
    "gcs_motora": "6", "duracion_de_la_perdida_de_conciencia": "00:10:00",
}
LABORATORIO_NUMERICO = {
    "globulos_blancos": "8.5", "hematocrito": "42", "hemoglobina": "14", "plaquetas": "250", "na": "140",
    "k": "4", "cl": "100", "hco3": "24", "bun": "15", "creatinina": "1", "glucosa": "100", "tp": "12",
    "tpt": "30", "inr": "1", "pao2": "90", "paco2": "40", "ph": "7.4", "be": "0", "deficit_de_base": "0",
    "lactato": "1.5",
}
LABORATORIO = {
    "fecha_y_hora_de_laboratorio": "2024-01-10 09:00", **LABORATORIO_NUMERICO,
    "tipo_de_sangre_y_factor_rh": "O+", "sangre_en_orina": "NEG", "anfetaminas": "NEGATIVO",
    "barbituricos": "NEGATIVO", "benzodiacepinas": "NEGATIVO", "cocaina": "NEGATIVO",
    "opiaceos": "NEGATIVO", "fenciclidina": "NEGATIVO", "mioglobinuria": None,  # columna 100 % nula
    "otras_drogas": "MARIHUANA",
}
SEVERIDAD = {"cabeza": "2", "cara": "0", "torax": "1", "abdomen": "0", "extremidades": "0",
             "externo": "0", "iss": "5"}

# Instrumento -> columnas de datos, en el orden del formulario; cada uno se cierra con <instrumento>_complete
ESQUEMA = {
    "informacion_demografica": ["nombre", "numero_de_identificacion", "fecha_de_nacimiento",
                                "fecha_y_hora_de_llegada_del_paciente", "edad", "genero", "tipo_de_seguro"],
    "motivo_de_consulta": ["motivo_de_consulta", "otras_sustancias_de_abuso"],
    "comorbilidades": ["co_morbilidades"],
    "mecanismo_de_lesion": ["scq", "altura_en_metros"],
    "signos_vitales": list(SIGNOS),
    "examen_fisico": ["hallazgo"],
    "puntuacion_de_severidad": list(SEVERIDAD),
    "imagenes": ["tipo_de_imagen", "descripcion"],
    "laboratorio": list(LABORATORIO),
    "hospitalizacion": ["fecha_de_admision", "fecha_y_hora_de_alta", "dias_de_hospitalizacion"],
    "complicaciones": ["complicaciones_de_hospitalizacion"],
    "cie_10_diagnosticos": ["codigo_cie_10_diagnostico_definitivo"],
    "procedimientos": ["fecha_y_hora_de_procedimiento", "fecha_y_hora_de_fin_procedimiento"],
    "liquidos": ["cristaloides", "coloides", "sangre"],
    "uci": ["fecha_y_hora_de_inicio_del_ventilador", "fecha_y_hora_de_termino_del_ventilador", "dias_usados"],
}
COLUMNAS = ["record_id", "redcap_repeat_instrument", "redcap_repeat_instance"] + [
    c for nombre, cols in ESQUEMA.items() for c in (*cols, f"{nombre}_complete")
]


def _demografia(nombre, documento, nacimiento, llegada, edad, genero, seguro="SEGURO-SINTETICO"):
    """El seguro vacío (`seguro=""`) comprueba la etiqueta que adopta REDCap del Excel ('No especificado')."""
    return {"nombre": nombre, "numero_de_identificacion": documento, "fecha_de_nacimiento": nacimiento,
            "fecha_y_hora_de_llegada_del_paciente": llegada, "edad": edad, "genero": genero,
            "tipo_de_seguro": seguro}


def _export_sintetico() -> pd.DataFrame:
    """Export plano ficticio: 3 episodios, los 15 instrumentos y filas de instrumentos repetibles."""
    filas = [
        # Episodio 1: fila principal con los instrumentos no repetibles
        {"record_id": "1",
         **_demografia("Persona Uno", "CC-9X7Z", "1990-05-01", "2024-01-10 08:30", "34", "M"),
         "motivo_de_consulta": "trauma de prueba", "otras_sustancias_de_abuso": "marihuna", "co_morbilidades": "R31 HEMATURIA NO ESPECIFICADA",
         "scq": "2", "altura_en_metros": "1.5", **SIGNOS, "hallazgo": "sin hallazgos", **SEVERIDAD,
         "fecha_de_admision": "2024-01-10", "fecha_y_hora_de_alta": "2024-01-15 12:00:00",
         "dias_de_hospitalizacion": "5", "complicaciones_de_hospitalizacion": "I46 PARO CARDIACO",
         "cristaloides": "1.5", "coloides": "0.5", "sangre": "0.5",
         "fecha_y_hora_de_inicio_del_ventilador": "2024-01-10 12:00",
         "fecha_y_hora_de_termino_del_ventilador": "2024-01-12 12:00", "dias_usados": "2"},
        # Episodio 1: instrumentos repetibles
        {"record_id": "1", "redcap_repeat_instrument": "imagenes", "redcap_repeat_instance": "1",
         "tipo_de_imagen": "RX", "descripcion": "torax"},
        {"record_id": "1", "redcap_repeat_instrument": "laboratorio", "redcap_repeat_instance": "1", **LABORATORIO},
        {"record_id": "1", "redcap_repeat_instrument": "cie_10_diagnosticos", "redcap_repeat_instance": "1",
         "codigo_cie_10_diagnostico_definitivo": "T07 TRAUMATISMOS MULTIPLES, NO ESPECIFICADOS"},
        {"record_id": "1", "redcap_repeat_instrument": "procedimientos", "redcap_repeat_instance": "1",
         "fecha_y_hora_de_procedimiento": "2024-01-10 10:00",
         "fecha_y_hora_de_fin_procedimiento": "2024-01-10 11:30"},
        # Episodio 2: mismo documento con otro formato, otra llegada
        {"record_id": "2",
         **_demografia("Persona Dos", "cc 9x7z", "1937-03-02", "2024-02-01 20:00", "87", "F"),
         "fecha_de_admision": "2024-02-01", "fecha_y_hora_de_alta": "2024-02-03 10:00:00",
         "dias_de_hospitalizacion": "2"},
        # Episodio 3: solo datos demográficos (un vacío textual para ejercitar la limpieza)
        {"record_id": "3",
         **_demografia("Persona Tres", "CC-4W2Q", "2018-07-09", "2024-03-05 14:00", "5", "", seguro="")},
    ]
    return pd.DataFrame(filas, columns=COLUMNAS)


@pytest.fixture
def export_sintetico():
    """
    Crea un export REDCap ficticio en memoria (3 episodios, 15 instrumentos, nombres ya normalizados).
    Todos los valores y documentos son inventados: no hay datos clínicos ni identificadores reales.
    """
    return _export_sintetico()


@pytest.fixture
def yaml_vacio(tmp_path):
    """Crea un YAML de renombres vacío en un directorio temporal aislado (el export ya trae los nombres finales)."""
    ruta = tmp_path / "renombres.yaml"
    ruta.write_text("", encoding="utf-8")
    return str(ruta)


@pytest.fixture
def crear_transformer(yaml_vacio):
    """Devuelve una función que arma un REDCapTransformer sobre particiones en memoria y el YAML vacío."""
    def _crear(particiones):
        return REDCapTransformer(CLAVE_SINTETICA, particiones=particiones, renombres_yaml=yaml_vacio)
    return _crear


@pytest.fixture
def resultado(crear_transformer, export_sintetico):
    """Ejecuta run() una vez sobre el export sintético (una sola partición)."""
    return crear_transformer({PARTICION_ANTIGUA: export_sintetico}).run()


class TestRedcapTransformerSalida:
    def test_devuelve_una_tabla_por_instrumento(self, resultado):
        """
        Qué es: prueba de humo y de integración interna del REDCapTransformer (extremo a extremo, sin disco).
        Qué hace: ejecuta run() sobre el export sintético y lista las tablas de salida.
        Esperado: una tabla por cada uno de los 15 instrumentos esperados, y los 3 episodios en la tabla base.
        """
        # Arrange: el fixture "resultado" ya ejecutó run()

        # Act: no aplica, el resultado viene del fixture

        # Assert: el contrato de salida es una tabla por instrumento, con el episodio como grano base
        assert set(resultado.tables) == set(INSTRUMENTOS_ESPERADOS)
        assert resultado.rows["informacion_demografica"] == 3

    def test_llaves_canonicas(self, resultado):
        """
        Qué es: prueba del namespacing de llaves aplicado por BaseTransformer.run().
        Qué hace: inspecciona las columnas de llave de la tabla base y de las tablas hijas.
        Esperado: la tabla base lleva trauma_register_id, source_record_id y source_system (RC-1..RC-3);
                  las hijas solo trauma_register_id; ninguna conserva record_id.
        """
        # Arrange: tablas del resultado
        tablas = resultado.tables

        # Act: no aplica, se inspeccionan las salidas

        # Assert: llaves canónicas y sin record_id en ninguna tabla
        base = tablas["informacion_demografica"]
        assert list(base.columns[:3]) == ["trauma_register_id", "source_record_id", "source_system"]
        assert sorted(base["trauma_register_id"]) == ["RC-1", "RC-2", "RC-3"]
        assert set(base["source_system"]) == {"redcap"}
        assert "source_record_id" not in tablas["signos_vitales"].columns
        assert tablas["signos_vitales"]["trauma_register_id"].tolist() == ["RC-1"]
        assert all("record_id" not in df.columns for df in tablas.values())

    def test_tipos_y_derivadas(self, resultado):
        """
        Qué es: prueba de las transformaciones por instrumento sobre datos sintéticos.
        Qué hace: revisa tipos y valores derivados de demografía, signos vitales, laboratorio y procedimientos.
        Esperado: fechas en datetime; quinquenio y orden correctos (30-34/6, 85 o más/17, 5-9/1);
                  GCS en Int64; toxicología en boolean; duración del procedimiento 5400 s (1,5 h).
        """
        # Arrange: tablas del resultado
        tablas = resultado.tables

        # Act: no aplica, se inspeccionan las salidas

        # Assert: tipos del modelo y derivadas correctas
        dem = tablas["informacion_demografica"].set_index("source_record_id")
        assert pd.api.types.is_datetime64_any_dtype(dem["fecha_y_hora_de_llegada_del_paciente"])
        assert dem["quinquenio_edad"].to_dict() == {"1": "30-34", "2": "85 o más", "3": "5-9"}
        assert dem["quinquenio_orden"].to_dict() == {"1": 6, "2": 17, "3": 1}
        assert str(tablas["signos_vitales"]["gcs_total"].dtype) == "Int64"
        assert str(tablas["laboratorio"]["cocaina"].dtype) == "boolean"
        assert tablas["procedimientos"]["duracion_procedimiento_seg"].tolist() == [5400]

    def test_elimina_columnas_de_sistema_y_sensibles(self, resultado):
        """
        Qué es: prueba de minimización de datos en la salida del transformer.
        Qué hace: busca en todas las tablas las columnas de sistema, los identificadores directos y la edad exacta.
        Esperado: ninguna tabla conserva redcap_repeat_*, nombre, numero_de_identificacion,
                  fecha_de_nacimiento ni edad.
        """
        # Arrange: columnas prohibidas en la salida
        prohibidas = {"redcap_repeat_instrument", "redcap_repeat_instance", "nombre",
                      "numero_de_identificacion", "fecha_de_nacimiento", "edad"}

        # Act: no aplica, se inspeccionan las salidas

        # Assert: ninguna tabla las contiene
        for nombre, df in resultado.tables.items():
            assert not (prohibidas & set(df.columns)), nombre


class TestRedcapTransformerPrivacidad:
    def test_documento_no_aparece_en_ninguna_tabla(self, resultado):
        """
        Qué es: prueba de privacidad (Habeas Data) sobre la salida completa.
        Qué hace: busca los documentos sintéticos (en cualquiera de sus formatos) en el texto de todas las celdas.
        Esperado: no aparece ninguno; solo existe el seudónimo.
        """
        # Arrange: fragmentos de los documentos sintéticos, que contienen letras que un hexadecimal no tiene
        patron = "9X7Z|9x7z|4W2Q"

        # Act: texto de cada tabla, con los nulos como cadena vacía
        # Assert: ninguna celda contiene el documento
        for nombre, df in resultado.tables.items():
            texto = df.astype("string").fillna("")
            hallazgos = texto.apply(lambda col: col.str.contains(patron, regex=True))
            assert not hallazgos.to_numpy().any(), nombre

    def test_mismo_documento_produce_el_mismo_seudonimo(self, resultado):
        """
        Qué es: prueba de consistencia de la seudonimización.
        Qué hace: compara el seudónimo de los episodios 1 y 2 (mismo documento con distinto formato) y el del 3.
        Esperado: los episodios 1 y 2 comparten seudónimo (normalización) y el 3 es distinto.
        """
        # Arrange: seudónimos por episodio
        dem = resultado.tables["informacion_demografica"].set_index("source_record_id")
        seudonimos = dem["documento_seudonimo"]

        # Act: no aplica, se leen las salidas

        # Assert: 'CC-9X7Z' y 'cc 9x7z' normalizan igual; otro documento da otro valor
        assert seudonimos["1"] == seudonimos["2"]
        assert seudonimos["3"] != seudonimos["1"]


class TestRedcapTransformerReporte:
    def test_auditoria_conserva_y_el_reporte_esta_completo(self, resultado):
        """
        Qué es: prueba del reporte de calidad producido por una corrida completa.
        Qué hace: revisa auditoría, consolidación, resumen de bloques y perfiles del reporte.
        Esperado: toda variable auditada conserva sus datos; hay 1 consolidación, 15 filas de resumen de bloques
                  y perfiles en las etapas "antes" y "despues".
        """
        # Arrange: reporte del resultado
        reporte = resultado.reporte

        # Act: no aplica, se inspecciona el reporte

        # Assert: trazabilidad completa de la corrida
        assert not reporte.tabla("auditoria").empty
        assert reporte.tabla("auditoria")["conserva"].all()
        assert len(reporte.consolidacion) == 1
        assert len(reporte.resumen_bloques) == 15
        assert {p["etapa"] for p in reporte.perfiles} == {"antes", "despues"}

    def test_filas_de_cada_bloque_mas_descartadas_igualan_la_foto(self, resultado):
        """
        Qué es: prueba de conservación de filas en la división en bloques de una corrida completa
                (las filas descartadas también se cuentan).
        Qué hace: suma, por instrumento, las filas del bloque (resumen_bloques) y las descartadas (descartes).
        Esperado: la suma es igual a las filas vigentes de la consolidación en los 15 instrumentos; el
                  descarte de filas sin datos queda contado en el reporte y no es silencioso.
        """
        # Arrange: reporte del resultado y filas de la foto consolidada
        reporte = resultado.reporte
        filas_foto = reporte.consolidacion[0]["filas_vigentes"]
        descartes = reporte.tabla("descartes").groupby("instrumento")["filas_descartadas"].sum()

        # Act: no aplica, se inspecciona el reporte

        # Assert: filas conservadas + descartadas = filas de la foto, por instrumento
        for fila in reporte.resumen_bloques:
            assert fila["n_filas"] + descartes.get(fila["instrumento"], 0) == filas_foto, fila["instrumento"]

    def test_duplicados_marcados_en_los_tres_niveles(self, resultado):
        """
        Qué es: prueba del marcado de duplicados en el orquestador.
        Qué hace: lee el resumen de duplicados de la corrida.
        Esperado: se evaluaron los tres niveles y el export sintético no tiene duplicados en ninguno.
        """
        # Arrange: resumen del reporte
        resumen = resultado.reporte.tabla("resumen_duplicados")

        # Act: no aplica, se lee el reporte

        # Assert: fila exacta, clave estructural y regla de negocio, todos únicos
        assert resumen["nivel"].tolist() == ["fila_exacta", "clave_estructural", "regla_negocio"]
        assert resumen["es_unica"].all()

    def test_cronologia_sin_incumplimientos_con_datos_validos(self, resultado):
        """
        Qué es: prueba de las verificaciones cronológicas con un export coherente.
        Qué hace: lee las reglas del bloque "cronologia" del reporte.
        Esperado: existen reglas de cronología y ninguna registra filas que incumplen.
        """
        # Arrange: reglas del reporte
        reglas = resultado.reporte.tabla("reglas")
        cronologia = reglas[reglas["bloque"] == "cronologia"]

        # Act: no aplica, se lee el reporte

        # Assert: fechas ordenadas y dentro de la estancia en el export sintético
        assert not cronologia.empty
        assert (cronologia["filas_que_incumplen"] == 0).all()

    def test_procedencia_de_la_corrida(self, resultado):
        """
        Qué es: prueba de reproducibilidad del REDCapTransformer (procedencia que va al manifiesto).
        Qué hace: lee la procedencia del resultado de la corrida sintética (una partición en memoria).
        Esperado: la partición consolidada, la huella del YAML de renombres usado (temporal) y de los catálogos, y la
                  versión del código (commit y si había cambios sin commit).
        """
        # Arrange
        procedencia = resultado.procedencia

        # Act: no aplica, se lee el resultado

        # Assert
        assert procedencia["particiones_raw"] == [PARTICION_ANTIGUA]
        assert any(r.endswith("renombres.yaml") for r in procedencia["configuracion"])
        assert any(r.startswith("config/catalogos/") for r in procedencia["configuracion"])
        assert set(procedencia["codigo"]) == {"commit", "cambios_sin_commit"}

    def test_identificadores_excluidos_quedan_en_exclusiones(self, resultado):
        """
        Qué es: prueba de trazabilidad de los identificadores directos que la división deja fuera (decisión 2.8).
        Qué hace: lee la tabla `exclusiones` del reporte de la corrida sintética.
        Esperado: nombre y fecha de nacimiento (las columnas de EXCLUIR_DEL_DW que trae el export) aparecen en el bloque
                  global con 3 filas con valor cada una y su motivo; las que el export no trae no se registran.
        """
        # Arrange
        exclusiones = resultado.reporte.tabla("exclusiones").set_index("columna")

        # Act: no aplica, se lee el reporte

        # Assert
        assert sorted(exclusiones.index) == ["fecha_de_nacimiento", "nombre"]
        assert (exclusiones["filas_con_valor"] == 3).all()
        assert (exclusiones["bloque"] == "global").all()


class TestRedcapTransformerIdempotencia:
    def test_dos_ejecuciones_dan_el_mismo_resultado(self, crear_transformer, export_sintetico):
        """
        Qué es: prueba de idempotencia del transformer.
        Qué hace: ejecuta run() dos veces sobre las mismas particiones, con instancias distintas.
        Esperado: las tablas de salida, la auditoría y las reglas son idénticas.
        """
        # Arrange: dos transformers independientes sobre los mismos datos
        particiones = {PARTICION_ANTIGUA: export_sintetico}

        # Act: ejecutar dos veces
        primero = crear_transformer(particiones).run()
        segundo = crear_transformer(particiones).run()

        # Assert: misma entrada y mismo código dan el mismo resultado (transformed_at es metadata y se excluye)
        assert set(primero.tables) == set(segundo.tables)
        for nombre in primero.tables:
            pd.testing.assert_frame_equal(primero.tables[nombre], segundo.tables[nombre])
        for tabla in ("auditoria", "reglas"):
            pd.testing.assert_frame_equal(primero.reporte.tabla(tabla), segundo.reporte.tabla(tabla))

    def test_no_modifica_las_particiones_de_entrada(self, crear_transformer, export_sintetico):
        """
        Qué es: prueba de que la capa raw (aquí simulada en memoria) no se altera.
        Qué hace: ejecuta run() y compara el DataFrame de entrada con una copia hecha antes.
        Esperado: el DataFrame de entrada queda idéntico.
        """
        # Arrange: copia de referencia de la entrada
        copia = export_sintetico.copy()

        # Act: ejecutar
        crear_transformer({PARTICION_ANTIGUA: export_sintetico}).run()

        # Assert: la transformación trabaja sobre copias, nunca sobre la fuente
        pd.testing.assert_frame_equal(export_sintetico, copia)


class TestRedcapTransformerConsolidacion:
    def test_usa_la_version_mas_reciente_del_registro(self, crear_transformer, export_sintetico):
        """
        Qué es: prueba de la integración de la consolidación en el transformer.
        Qué hace: agrega una partición posterior con el episodio 2 modificado (género distinto) y ejecuta run().
        Esperado: el episodio 2 sale con el valor nuevo, el episodio 1 conserva el antiguo y el resumen cuenta
                  1 registro presente en más de una partición.
        """
        # Arrange: partición nueva con el registro 2 completo y un género modificado
        nuevo = export_sintetico[export_sintetico["record_id"] == "2"].copy()
        nuevo["genero"] = "NB"
        particiones = {PARTICION_ANTIGUA: export_sintetico, PARTICION_NUEVA: nuevo}

        # Act: ejecutar
        resultado = crear_transformer(particiones).run()

        # Assert: gana la versión de la partición más reciente, por registro
        dem = resultado.tables["informacion_demografica"].set_index("source_record_id")
        assert dem.loc["2", "genero"] == "NB"
        assert dem.loc["1", "genero"] == "M"
        assert resultado.reporte.consolidacion[0]["record_id_en_mas_de_una_particion"] == 1


class TestRedcapTransformerConstruccion:
    @pytest.mark.parametrize("clave", [None, ""])
    def test_sin_clave_lanza_valueerror(self, clave):
        """
        Qué es: prueba de validación del constructor de REDCapTransformer.
        Qué hace: crea el transformer sin clave de seudonimización (None y cadena vacía).
        Esperado: lanza ValueError; no se puede transformar sin poder seudonimizar el documento.
        """
        # Arrange: clave ausente (parámetro)

        # Act + Assert: debe rechazarlo de inmediato, sin leer ninguna partición
        with pytest.raises(ValueError):
            REDCapTransformer(clave, particiones={})


class TestTransformerFactory:
    def test_crea_el_transformer_de_redcap(self, export_sintetico, yaml_vacio):
        """
        Qué es: prueba de TransformerFactory.get_transformer (caso normal).
        Qué hace: pide el transformer "redcap" (en minúsculas y con otro uso de mayúsculas) con su configuración.
        Esperado: devuelve una instancia de REDCapTransformer en ambos casos.
        """
        # Arrange: configuración mínima con particiones sintéticas
        config = {"clave_seudonimizacion": CLAVE_SINTETICA, "renombres_yaml": yaml_vacio,
                  "particiones": {PARTICION_ANTIGUA: export_sintetico}}

        # Act: crear con dos capitalizaciones
        a = TransformerFactory.get_transformer("redcap", config)
        b = TransformerFactory.get_transformer("REDCap", config)

        # Assert: el registro no distingue mayúsculas y apunta a la clase, no al módulo
        assert isinstance(a, REDCapTransformer)
        assert isinstance(b, REDCapTransformer)

    def test_origen_desconocido_lanza_valueerror(self):
        """
        Qué es: prueba de validación de TransformerFactory.get_transformer.
        Qué hace: pide un origen no registrado.
        Esperado: lanza ValueError con el listado de orígenes disponibles.
        """
        # Arrange: origen que no existe

        # Act + Assert: debe fallar con un mensaje claro
        with pytest.raises(ValueError, match="redcap"):
            TransformerFactory.get_transformer("sql", {})

    def test_configuracion_invalida_lanza_typeerror(self):
        """
        Qué es: prueba de validación de configuración en TransformerFactory.get_transformer.
        Qué hace: crea el transformer "redcap" con un parámetro que su constructor no acepta.
        Esperado: lanza TypeError con un mensaje que nombra el origen.
        """
        # Arrange: configuración con una clave desconocida
        config = {"clave_seudonimizacion": CLAVE_SINTETICA, "parametro_inexistente": 1}

        # Act + Assert: la fábrica debe reportar la configuración inválida
        with pytest.raises(TypeError, match="redcap"):
            TransformerFactory.get_transformer("redcap", config)
