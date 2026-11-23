import pandas as pd
import pytest
import yaml

from config.settings import EXCEL_MAPEO_YAML_PATH
from etl import pipeline
from etl.transform.common.cie10 import cargar_universo
from etl.transform.excel.preparacion import EXCLUIR_DEL_DW
from etl.transform.excel_transformer import ExcelTransformer
from etl.transform.factory import TransformerFactory

CLAVE_SINTETICA = "clave-sintetica-de-prueba-0123456789"
K = "traumaregisterrecordid"
# Columnas del mapeo que la transformación CREA (no vienen en la hoja cruda)
DERIVADAS = {"documento_seudonimo", "historia_seudonimo", "quinquenio_edad", "quinquenio_orden"}
CRUDAS_EXTRA = ["numero_de_identificacion", "numero_de_historia_clinica", "edad", "unidad_de_edad"]
IDENTIFICADORES = {"numero_de_identificacion", "numero_de_historia_clinica", "nombre", "apellido_paterno",
                   "apellido_materno", "fecha_de_nacimiento", "edad", "direccion_linea_1", "direccion_linea_2"}


def _registro_trauma() -> pd.DataFrame:
    """registro_trauma ficticio con TODAS las columnas que espera el mapeo (nombres ya normalizados) y 3 atenciones.
    Casi todo vacío; solo se llenan los valores que ejercitan reglas. Documentos y textos inventados."""
    mapeo = yaml.safe_load(open(EXCEL_MAPEO_YAML_PATH, encoding="utf-8"))["registro_trauma"]
    columnas = [K] + [c for cols in mapeo.values() for c in cols if c not in DERIVADAS] + EXCLUIR_DEL_DW + CRUDAS_EXTRA
    df = pd.DataFrame({c: [None] * 3 for c in columnas}, dtype=object)
    df[K] = ["1", "2", "3"]
    df["numero_de_identificacion"] = ["CC-9X7Z", "CC-4W2Q", None]
    df["numero_de_historia_clinica"] = ["H-111", None, None]
    df["fecha_y_hora_de_llegada_del_paciente"] = ["10/01/2020 08:30:00", "01/02/2020 20:00:00", "05/03/2020 14:00:00"]
    df["fecha_de_admision"] = ["10/01/2020", None, None]
    df["fecha_y_hora_de_alta"] = ["15/01/2020 12:00:00", None, None]
    df["dias_de_hospitalizacion"] = ["5", None, None]
    df["edad"], df["unidad_de_edad"] = ["34", "8", None], ["Años", "Meses", None]
    df["ciudad"], df["provincia_estado"] = ["Cali", None, None], ["Valle del Cauca", None, None]
    df["caida"] = ["Si", None, None]
    df["uci_dias"] = ["2", None, None]
    df["direccion_nombre_del_lugar"] = ["Casa calle 4 # 12-34", None, None]
    df["disposicion_o_destino_del_paciente_hospitalizacion"] = ["Referido a otro hospital", None, None]
    return df


def _hojas_sinteticas() -> dict[str, pd.DataFrame]:
    """Las 18 hojas de la carga histórica con nombres ya normalizados y valores inventados (sin datos reales)."""
    sv = {"recordid": ["SV-1"], K: ["1"], "fecha_y_hora_de_signos_vitales": ["10/01/2020 08:45:00"],
          "signos_de_vida": ["Si"], "frecuencia_cardiaca": ["88"], "presion_arterial_sistolica": ["120"],
          "presion_arterial_diastolica": ["80"], "frecuencia_respiratoria": ["18"],
          "calificador_de_la_frecuencia_respiratoria": ["Frecuencia Respiratoria Asistida"], "temperatura": ["36.5"],
          "peso": ["70"], "altura": ["1.7"], "saturacion_de_oxigeno": ["97"], "perdida_de_conciencia": ["No"],
          # Etiquetas cambiadas como en el origen: "gcs_ocular" trae la verbal (1-5) y "gcs_verbal" la ocular (1-4)
          "duracion_de_la_perdida_de_conciencia": [None], "gcs_motora": ["6"], "gcs_ocular": ["5"],
          "gcs_verbal": ["4"], "gcs_total": ["15"], "avup": ["Paciente Responde A Dolor"]}
    lab = pd.DataFrame({
        K: ["1", "1", "1", "1"],
        "nombre_del_laboratorio": ["Hct- Hematocrito (%)", "Hb- Hemoglobina (g/dl)", "Plaquetas", "Alcoholemia (mg/dl)"],
        "nombre_de_la_unidad_de_laboratorio": ["%", "g/dl", "10E12L", "mg/dl"],
        "resultado_de_laboratorio": ["42", "14", "250000", "10"],
        "fecha_y_hora_de_laboratorio": ["10/01/2020 09:00:00"] * 4})
    return {
        "registro_trauma": _registro_trauma(),
        "abuso_sustancias": pd.DataFrame({K: ["1"], "tipo_de_droga": ["F1. Marihuana"]}),
        "arma_blanca": pd.DataFrame({K: ["2"], "tipo_de_lesion_penetrante": ["Cortes/Laceraciones"]}),
        "arma_fuego": pd.DataFrame({K: ["2"], "tipo_de_arma_de_fuego": ["Pistola/revolver"]}),
        "calificador_gcs": pd.DataFrame({K: ["1"], "calificador_gcs": ["Otro calificador"]}),
        "codigos_cie10": pd.DataFrame({K: ["1", "1", "2"],
                                       "descripcion": ["Texto sin pareja de prueba", "Otro texto", "Referencia"],
                                       "mecanismo_icd": ["Final Diagnosis and Organ Injury Scale", "Co-morbidities",
                                                         "Reference"]}),
        "colisiones": pd.DataFrame({K: ["1"], "tipo_de_colision": ["Peatón vs. Bicileta"]}),
        "complicaciones_hospitalizacion": pd.DataFrame({K: ["1"], "tipo_de_complicacion": ["Complicacion inventada"],
                                                        "fecha_y_hora_de_complicacion": ["12/01/2020 10:00:00"],
                                                        "lugar_de_complicacion": ["UCI"]}),
        "envenenamiento": pd.DataFrame({K: ["3"], "tipo_de_envenenamiento": ["Mordedura/contacto de serpiente"]}),
        "imagenes": pd.DataFrame({K: ["1"], "tipo_de_imagen": ["Ultra Sonido"], "parte_del_cuerpo": ["Tórax"],
                                  "opcion": ["x"], "descripcion_imagen": ["sin hallazgos"]}),
        "procedimientos": pd.DataFrame({K: ["1"], "procedimiento_realizado": [" lavado quirurgico "],
                                        "fecha_y_hora_de_procedimiento": ["10/01/2020 10:00:00"],
                                        "fecha_y_hora_de_fin_procedimiento": ["10/01/2020 11:30:00"],
                                        "lugar": ["Quirofano"]}),
        "procedimientos_prehospitalarios": pd.DataFrame({K: ["2"], "procedimiento_realizado": ["inmovilizacion"]}),
        "quemaduras": pd.DataFrame({K: ["3"], "tipo_de_quemadura": ["No especificada"], "grado_de_quemadura": ["1"]}),
        "signos_vitales": pd.DataFrame(sv),
        "tiempo_uci": pd.DataFrame({K: ["1"], "tipo": ["Ventilador Mecánico"],
                                    "fecha_y_hora_de_inicio": ["10/01/2020 12:00:00"],
                                    "fecha_y_hora_de_termino": ["12/01/2020 12:00:00"],
                                    "lugar": ["UCI de Quemados"], "uci_dias": ["2"]}),
        "tipo_violencia": pd.DataFrame({K: ["2"], "parte_del_cuerpo": ["Tórax"], "tipo_de_lesion": ["Fractura cerrada"]}),
        "violencia": pd.DataFrame({K: ["2"], "tipo_de_violencia": ["Interpersonal"]}),
        "laboratorio": lab,
    }


@pytest.fixture(scope="module")
def universo():
    """Universo CIE-10 (catálogo y lista completa de REDCap: información pública, sin datos clínicos), cargado una vez."""
    return cargar_universo()


@pytest.fixture
def yaml_vacio(tmp_path):
    """Crea un YAML de renombres vacío en un directorio temporal aislado (las hojas ya traen los nombres finales)."""
    ruta = tmp_path / "renombres.yaml"
    ruta.write_text("", encoding="utf-8")
    return str(ruta)


@pytest.fixture
def crear_transformer(yaml_vacio, universo):
    """Devuelve una función que arma un ExcelTransformer sobre hojas en memoria (sin disco)."""
    def _crear(hojas):
        return ExcelTransformer(CLAVE_SINTETICA, renombres_yaml=yaml_vacio, hojas=hojas, universo_cie10=universo)
    return _crear


@pytest.fixture
def resultado(crear_transformer):
    """Ejecuta run() una vez sobre las 18 hojas sintéticas."""
    return crear_transformer(_hojas_sinteticas()).run()


class TestExcelTransformerSalida:
    def test_tablas_de_bloques_y_hojas(self, resultado):
        """
        Qué es: prueba de humo e integración interna del ExcelTransformer (extremo a extremo, sin disco).
        Qué hace: ejecuta run() sobre el Excel sintético y lista las tablas de salida.
        Esperado: los bloques de registro_trauma con columnas propias y las hojas hijas; la hoja 5 separada en sus
                  cuatro tablas por campo (codigos_cie10 ya no existe); los bloques vacíos no salen; la tabla base
                  tiene las 3 atenciones con llave EX-.
        """
        # Arrange + Act: el fixture "resultado" ya ejecutó run()
        tablas = resultado.tables

        # Assert: contrato de salida
        assert {"informacion_demografica", "hospitalizacion", "atencion_urgencias", "identificadores_pendientes",
                "signos_vitales", "laboratorio", "tiempo_uci", "cie_10_diagnostico_definitivo", "cie_10_comorbilidades",
                "cie10_mecanismos_de_lesiones_de_transito", "cie_10_otros_mecanismos_de_lesion_excluye_transito",
                "codigos_cie10_fuera_de_modelo"} <= set(tablas)
        assert "codigos_cie10" not in tablas and "hallazgos_pendientes" not in tablas
        assert sorted(tablas["informacion_demografica"]["trauma_register_id"]) == ["EX-1", "EX-2", "EX-3"]
        assert resultado.source_type == "excel"

    def test_sin_identificadores_directos_y_con_seudonimos(self, resultado):
        """
        Qué es: prueba de privacidad del ExcelTransformer (Habeas Data, minimización).
        Qué hace: busca en todas las tablas de salida las columnas identificadoras del Excel.
        Esperado: ninguna tabla trae documento, historia, nombres, nacimiento, edad exacta ni direcciones; la base
                  trae los seudónimos (64 caracteres hex) y no el documento original.
        """
        # Arrange
        tablas = resultado.tables

        # Act
        presentes = {c for df in tablas.values() for c in df.columns} & IDENTIFICADORES

        # Assert
        assert presentes == set()
        seudonimo = tablas["informacion_demografica"]["documento_seudonimo"]
        assert seudonimo.dropna().str.fullmatch(r"[0-9a-f]{64}").all()
        assert "CC-9X7Z" not in set(seudonimo.dropna())

    def test_nombres_comunes_con_redcap(self, resultado):
        """
        Qué es: prueba de los renombres acordados con REDCap (2026-10-22).
        Qué hace: revisa las columnas de las tablas que cambiaron de nombre.
        Esperado: ciudad estandarizada en MAYÚSCULAS, lesiones_de_caidas, parte_del_cuerpo_imagenes,
                  lugar_procedimiento, lugar_uci y fechas *_del_ventilador; dias_usados_uci entero.
        """
        # Arrange
        t = resultado.tables

        # Act: no aplica, se leen las tablas

        # Assert
        assert t["informacion_demografica"]["ciudad"].iloc[0] == "CALI"
        assert "lesiones_de_caidas" in t["mecanismo_de_lesion"]
        assert "parte_del_cuerpo_imagenes" in t["imagenes"] and "opcion" not in t["imagenes"]
        assert "lugar_procedimiento" in t["procedimientos"]
        assert {"lugar_uci", "fecha_y_hora_de_inicio_del_ventilador", "dias_usados_ventilador"} <= set(t["tiempo_uci"])
        assert str(t["uci"]["dias_usados_uci"].dtype) == "Int64"

    def test_glasgow_ocular_y_verbal_intercambiados(self, resultado):
        """
        Qué es: prueba de la corrección de etiquetas de Glasgow de la hoja 13 (decisión 3.16).
        Qué hace: transforma una fila sintética cuyo "gcs_ocular" trae 5 (fuera de 1-4) y "gcs_verbal" trae 4.
        Esperado: tras el intercambio, ocular = 4 y verbal = 5 sin valores invalidados por rango; el intercambio queda
                  en `renombres` en ambos sentidos.
        """
        # Arrange
        sv = resultado.tables["signos_vitales"]
        renombres = resultado.reporte.tabla("renombres")

        # Act
        de_hoja = renombres[renombres["bloque"] == "signos_vitales"].set_index("columna_original")["columna_nueva"]
        auditoria = resultado.reporte.tabla("auditoria").set_index(["bloque", "columna"])

        # Assert
        assert (sv["gcs_ocular"].iloc[0], sv["gcs_verbal"].iloc[0]) == (4, 5)
        assert (de_hoja["gcs_ocular"], de_hoja["gcs_verbal"]) == ("gcs_verbal", "gcs_ocular")
        assert auditoria.loc[("signos_vitales_hoja", "gcs_ocular"), "fuera_de_rango"] == 0

    def test_laboratorio_una_fila_por_toma(self, resultado):
        """
        Qué es: prueba de la hoja 17 en el transformer (decisión 3.14).
        Qué hace: transforma 4 exámenes de una misma toma, uno que no está en REDCap y plaquetas en 10E12L.
        Esperado: una fila; alcoholemia eliminada; plaquetas 250000 -> 250 (10E3/uL); hematocrito y hemoglobina numéricos.
        """
        # Arrange
        lab = resultado.tables["laboratorio"]

        # Act: no aplica

        # Assert
        assert len(lab) == 1
        assert lab["plaquetas"].iloc[0] == 250
        assert lab["hematocrito"].iloc[0] == 42 and "alcoholemia" not in lab

    def test_auditoria_y_correcciones_registradas(self, resultado):
        """
        Qué es: prueba de trazabilidad del reporte de calidad.
        Qué hace: revisa la auditoría y las correcciones del reporte de la corrida.
        Esperado: ninguna variable con diferencia sin explicar (run() la verifica); la etiqueta de colisiones y la
                  limpieza de lugar_del_evento quedan contadas como corrección.
        """
        # Arrange
        reporte = resultado.reporte

        # Act
        correcciones = reporte.tabla("correcciones")

        # Assert
        assert reporte.tabla("auditoria")["conserva"].all()
        assert ((correcciones["bloque"] == "colisiones") & (correcciones["filas_afectadas"] == 1)).any()
        assert (correcciones["columna"] == "lugar_del_evento").any()

    def test_columnas_eliminadas_quedan_en_exclusiones(self, resultado):
        """
        Qué es: prueba de trazabilidad de las columnas eliminadas (tabla `exclusiones` del reporte).
        Qué hace: lee las exclusiones del reporte de la corrida sintética.
        Esperado: están todas las de EXCLUIR_DEL_DW, la edad y su unidad, y las quitadas en bloques y hojas (p. ej.
                  otro_grupo_etnico, direcciones, Glasgow del bloque 5, opcion); cada una con su motivo y el conteo de
                  filas con valor (la edad sintética trae 2).
        """
        # Arrange
        exclusiones = resultado.reporte.tabla("exclusiones")

        # Act
        por_columna = exclusiones.set_index(["bloque", "columna"])

        # Assert
        assert {("registro_trauma", c) for c in EXCLUIR_DEL_DW} <= set(por_columna.index)
        assert por_columna.loc[("registro_trauma", "edad"), "filas_con_valor"] == 2
        assert {("informacion_demografica", "otro_grupo_etnico"), ("identificadores_pendientes", "direccion_linea_1"),
                ("signos_vitales", "gcs_total"), ("imagenes", "opcion")} <= set(por_columna.index)
        assert exclusiones["motivo"].notna().all()

    def test_balance_de_filas_y_procedencia(self, resultado):
        """
        Qué es: prueba de trazabilidad de filas y de reproducibilidad (balance_filas y procedencia del resultado).
        Qué hace: lee el balance del reporte y la procedencia de la corrida sintética (hojas inyectadas, sin disco).
        Esperado: cada bloque conserva las 3 filas de registro_trauma; las tablas de la hoja 5 suman sus 3 filas;
                  laboratorio pasa de 4 filas a 1 toma; la procedencia trae las filas por hoja, partición None (no se
                  leyó raw), las huellas de los YAML usados y la versión del código.
        """
        # Arrange
        balance = resultado.reporte.tabla("balance_filas")
        procedencia = resultado.procedencia

        # Act
        cie = balance[balance["origen"] == "codigos_cie10"]
        lab = balance[balance["origen"] == "laboratorio"].iloc[0]
        registro = balance[balance["origen"] == "registro_trauma"]

        # Assert
        assert (registro["filas_salida"] == 3).all() and "informacion_demografica" in set(registro["tabla"])
        assert cie["filas_salida"].sum() == 3 and (cie["filas_entrada"] == 3).all()
        assert (lab["filas_entrada"], lab["filas_salida"]) == (4, 1)
        assert procedencia["particion_raw"] is None
        assert procedencia["filas_por_hoja"]["laboratorio"] == 4
        assert "config/mapeo_columnas_excel.yaml" in procedencia["configuracion"]
        assert set(procedencia["codigo"]) == {"commit", "cambios_sin_commit"}

    def test_reglas_de_estancia_y_ventilador_como_redcap(self, resultado):
        """
        Qué es: prueba de las reglas cronológicas compartidas con REDCap en el Excel (common/cronologia.py).
        Qué hace: lee las reglas del bloque "cronologia" y las del ventilador de la hoja tiempo_uci.
        Esperado: una regla de estancia por cada fecha de evento (signos vitales, laboratorio, procedimientos, ventilador
                  y complicación), sin incumplimientos con las fechas sintéticas, que caen dentro de la estancia; las
                  dos reglas del ventilador quedan en tiempo_uci.
        """
        # Arrange
        reglas = resultado.reporte.tabla("reglas")

        # Act
        estancia = reglas[(reglas["bloque"] == "cronologia") & reglas["regla"].str.contains("fuera de la estancia")]
        ventilador = reglas[reglas["bloque"] == "tiempo_uci"]["regla"]

        # Assert
        assert len(estancia) == 7
        assert (estancia["filas_que_incumplen"] == 0).all()
        assert ventilador.str.contains("solo una de las dos fechas").any()
        assert ventilador.str.contains("anterior al inicio").any()


class TestExcelTransformerValidaciones:
    def test_falta_una_hoja_detiene(self, crear_transformer):
        """
        Qué es: prueba de la validación de hojas esperadas.
        Qué hace: ejecuta run() sin la hoja de laboratorio.
        Esperado: ValueError que nombra la hoja faltante (un cambio en la carga histórica no se propaga).
        """
        # Arrange
        hojas = _hojas_sinteticas()
        del hojas["laboratorio"]

        # Act + Assert
        with pytest.raises(ValueError, match="laboratorio"):
            crear_transformer(hojas).run()

    def test_columna_sin_bloque_detiene(self, crear_transformer):
        """
        Qué es: prueba de la división de registro_trauma por el mapeo.
        Qué hace: agrega a registro_trauma una columna que el mapeo no asigna a ningún bloque.
        Esperado: ValueError que la lista en sin_asignar.
        """
        # Arrange
        hojas = _hojas_sinteticas()
        hojas["registro_trauma"]["columna_nueva_del_origen"] = None

        # Act + Assert
        with pytest.raises(ValueError, match="columna_nueva_del_origen"):
            crear_transformer(hojas).run()

    def test_sin_clave_no_se_construye(self):
        """
        Qué es: prueba del constructor del ExcelTransformer.
        Qué hace: lo construye sin clave de seudonimización.
        Esperado: ValueError (no se transforma sin seudonimizar).
        """
        # Arrange: no aplica

        # Act + Assert
        with pytest.raises(ValueError, match="clave"):
            ExcelTransformer(None, hojas={})

    def test_la_fabrica_lo_registra(self):
        """
        Qué es: prueba del registro del transformer en la fábrica.
        Qué hace: pide a TransformerFactory el origen "excel".
        Esperado: una instancia de ExcelTransformer.
        """
        # Arrange: no aplica

        # Act
        transformer = TransformerFactory.get_transformer("excel", {"clave_seudonimizacion": CLAVE_SINTETICA,
                                                                    "hojas": {}})

        # Assert
        assert isinstance(transformer, ExcelTransformer)


class TestRunTransformExcel:
    def test_pide_el_transformer_de_excel_y_escribe_staging(self, tmp_path, monkeypatch):
        """
        Qué es: prueba unitaria de run_transform_excel con transformer simulado (sin raw ni clave real).
        Qué hace: sustituye la fábrica por un doble que devuelve un TransformResult sintético y ejecuta la corrida.
        Esperado: la fábrica recibe el origen "excel" con la clave y la carpeta raw; queda el Parquet en staging y
                  el reporte en reports/excel/run_id=....
        """
        # Arrange: doble de la fábrica y resultado sintético
        from etl.transform.base import TransformResult
        from etl.transform.common.quality import ReporteCalidad
        llamadas = []
        tabla = pd.DataFrame({"trauma_register_id": ["EX-1"], "valor": [1]})
        resultado = TransformResult(tables={"informacion_demografica": tabla}, reporte=ReporteCalidad(),
                                    source_type="excel", rows={"informacion_demografica": 1}, elapsed_seconds=0.1,
                                    transformed_at="2026-10-22T10:00:00+00:00")

        class Falso:
            def run(self):
                return resultado

        monkeypatch.setattr(pipeline.TransformerFactory, "get_transformer",
                            staticmethod(lambda origen, config: llamadas.append((origen, config)) or Falso()))
        staging = tmp_path / "staging" / "excel"

        # Act
        pipeline.run_transform_excel(raw_dir=str(tmp_path / "raw"), staging_dir=str(staging),
                                     reports_dir=str(tmp_path / "reports"), clave_seudonimizacion="clave-de-prueba-16b")

        # Assert
        assert llamadas == [("excel", {"clave_seudonimizacion": "clave-de-prueba-16b", "raw_dir": str(tmp_path / "raw")})]
        pd.testing.assert_frame_equal(pd.read_parquet(staging / "informacion_demografica.parquet"), tabla)
        assert (tmp_path / "reports" / "excel" / "run_id=2026-10-22T100000").exists()
