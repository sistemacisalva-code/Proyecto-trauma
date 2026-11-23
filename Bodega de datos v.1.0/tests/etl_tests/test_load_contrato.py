import csv
from pathlib import Path
import re

import pytest
import yaml

from etl.load.warehouse.contrato import ContratoInvalido, leer_contrato

RAIZ = Path(__file__).resolve().parents[2]
CONTRATO_COMPLETO = RAIZ / "config" / "contratos" / "completo.yaml"
DDL_COMPLETO = RAIZ / "database" / "schema" / "02_tables_completo.sql"
# Salida de scripts/esquema_staging.py: solo nombres y tipos de Arrow (metadatos), sin filas ni valores. No está
# versionado (scripts/ está en .gitignore); sin él, la prueba que lo usa se omite
ESQUEMA_STAGING = RAIZ / "scripts" / "esquema_staging.csv"

# Tipo de la columna destino -> prefijos de tipo de Arrow que puede recibir sin conversión
COMPATIBLES = {"TEXT": ("string", "large_string"), "INTEGER": ("int",), "NUMERIC": ("int", "double", "float")}


def _o(excel, redcap) -> dict:
    return {"excel": excel, "redcap": redcap}


def _contrato() -> dict:
    """
    Contrato sintético válido con todas las piezas de la forma completa: tabla de varias filas con toma,
    calendario con etiquetas, dimensión, catálogo con miembro para lo no mapeado, hecho y puente por rol con
    secuencia, orden, bandera de mapeo y texto de lo no mapeado. Nombres inventados, sin relación con datos reales.
    """
    def staging():
        # Un mapa nuevo por fuente, para que un defecto en una no se copie a la otra
        return {
            "registro": {"grano": "atencion"},
            "signos": {"grano": "varias", "toma": "primera", "orden": ["fecha_signos"]},
            "codigos": {"grano": "varias"},
        }

    return {
        "modelo": "doble", "version": 1,
        "staging": {"excel": staging(), "redcap": staging()},
        "tablas": {
            "dim_fecha": {"tipo": "calendario", "columnas": {
                "fecha": {"generado": "fecha"},
                "es_festivo": {"generado": "es_festivo", "etiquetas": {"verdadero": "SI", "falso": "NO"}},
            }},
            "dim_perfil": {"tipo": "dimension", "columnas": {
                "genero": {"origen": _o("registro.genero", "registro.genero")},
                "avup": {"origen": _o("signos.avup", "signos.avup")},
            }},
            "dim_codigo": {"tipo": "catalogo", "columna": "codigo", "sin_mapeo": "SIN CODIGO"},
            "fact_doble": {"tipo": "hecho", "filas": _o("registro", "registro"), "columnas": {
                "trauma_register_id": {"origen": _o("registro.trauma_register_id", "registro.trauma_register_id")},
                "fecha_llegada_id": {"resolucion": "calendario", "origen": _o("registro.llegada", "registro.llegada")},
                "perfil_id": {"resolucion": "dimension", "dimension": "dim_perfil"},
                "pulso": {"origen": _o("signos.pulso", "signos.pulso")},
            }},
            "bridge_codigo": {"tipo": "puente", "por_rol": {"diagnostico": {
                "filas": _o("codigos", "codigos"),
                "orden": _o(["fecha_codigo"], None),
                "columnas": {
                    "secuencia": {"resolucion": "secuencia"},
                    "codigo_id": {"resolucion": "dimension", "dimension": "dim_codigo",
                                  "origen": _o("codigos.codigo", "codigos.codigo"),
                                  "mapeado": _o("codigos.mapeado", None)},
                    "texto_origen": {"resolucion": "texto_sin_mapeo", "de": "codigo_id"},
                },
            }}},
        },
    }


def _guardar(tmp_path, contrato: dict) -> str:
    ruta = tmp_path / "doble.yaml"
    ruta.write_text(yaml.safe_dump(contrato, allow_unicode=True), encoding="utf-8")
    return str(ruta)


def _esquema_valido() -> dict[str, dict[str, str]]:
    """Esquema sintético del staging en el que existe todo lo que pide _contrato(), con los tipos correctos."""
    return {
        "registro": {"trauma_register_id": "large_string", "genero": "large_string", "llegada": "timestamp[us]"},
        "signos": {"trauma_register_id": "large_string", "fecha_signos": "timestamp[us]", "avup": "large_string",
                   "pulso": "int64"},
        "codigos": {"trauma_register_id": "large_string", "fecha_codigo": "timestamp[us]",
                    "codigo": "large_string", "mapeado": "bool"},
    }


def _columnas_ddl() -> dict[str, dict[str, str]]:
    """{tabla: {columna: tipo SQL}} de cada CREATE TABLE del DDL del completo, sin las claves sustitutas."""
    texto = DDL_COMPLETO.read_text(encoding="utf-8")
    tablas = {}
    for tabla, cuerpo in re.findall(r"CREATE TABLE IF NOT EXISTS \w+\.(\w+) \((.*?)\n\);", texto, re.S):
        tablas[tabla] = {
            m.group(1): m.group(2)
            for m in (re.match(r"\s+(\w+)\s+(TEXT|INTEGER|NUMERIC|DATE)\b(.*)", linea) for linea in cuerpo.splitlines())
            if m and "GENERATED ALWAYS" not in m.group(3)
        }
    return tablas


def _esquema_staging_real() -> dict[str, dict[str, dict[str, str]]]:
    """{fuente: {tabla: {columna: tipo de Arrow}}} de la copia de metadatos del staging."""
    esquema: dict = {}
    with open(ESQUEMA_STAGING, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            esquema.setdefault(fila["fuente"], {}).setdefault(fila["tabla"], {})[fila["columna"]] = fila["tipo_arrow"]
    return esquema


# ---------------------------------------------------------------------------
# Defectos de la forma completa: cada uno modifica el contrato sintético válido
# ---------------------------------------------------------------------------

def _sin_toma(c):
    c["staging"]["excel"]["signos"] = {"grano": "varias"}


def _puente_a_tabla_de_varias(c):
    c["tablas"]["bridge_codigo"]["por_rol"]["diagnostico"]["columnas"]["pulso"] = {
        "origen": _o("signos.pulso", "signos.pulso")}


def _dimension_inexistente(c):
    c["tablas"]["fact_doble"]["columnas"]["perfil_id"]["dimension"] = "dim_nada"


def _catalogo_sin_origen(c):
    del c["tablas"]["bridge_codigo"]["por_rol"]["diagnostico"]["columnas"]["codigo_id"]["origen"]


def _dimension_con_origen(c):
    c["tablas"]["fact_doble"]["columnas"]["perfil_id"]["origen"] = _o("registro.genero", "registro.genero")


def _dimension_dos_veces(c):
    c["tablas"]["fact_doble"]["columnas"]["perfil_bis_id"] = {"resolucion": "dimension", "dimension": "dim_perfil"}


def _tabla_sin_declarar(c):
    del c["staging"]["redcap"]["signos"]


def _tabla_sin_uso(c):
    c["staging"]["excel"]["ajena"] = {"grano": "atencion"}


def _secuencia_en_hecho(c):
    c["tablas"]["fact_doble"]["columnas"]["secuencia"] = {"resolucion": "secuencia"}


def _mapeado_sin_miembro(c):
    del c["tablas"]["dim_codigo"]["sin_mapeo"]


def _festivo_sin_comillas(c):
    # Así llega `falso: NO` sin comillas: YAML 1.1 lo lee como booleano
    c["tablas"]["dim_fecha"]["columnas"]["es_festivo"]["etiquetas"]["falso"] = False


def _toma_en_grano_atencion(c):
    c["staging"]["excel"]["registro"]["toma"] = "primera"


def _hecho_sin_filas_en_una_fuente(c):
    c["tablas"]["fact_doble"]["filas"]["redcap"] = None


def _texto_de_columna_sin_bandera(c):
    c["tablas"]["bridge_codigo"]["por_rol"]["diagnostico"]["columnas"]["texto_origen"]["de"] = "secuencia"


def _texto_con_origen_propio(c):
    c["tablas"]["bridge_codigo"]["por_rol"]["diagnostico"]["columnas"]["texto_origen"]["origen"] = _o(
        "codigos.codigo", "codigos.codigo")


def _orden_sin_secuencia(c):
    del c["tablas"]["bridge_codigo"]["por_rol"]["diagnostico"]["columnas"]["secuencia"]


DEFECTOS = [
    (_sin_toma, "declare 'toma: primera'"),
    (_puente_a_tabla_de_varias, "un puente solo se une a tablas de grano atencion"),
    (_dimension_inexistente, "no es una dimensión ni un catálogo"),
    (_catalogo_sin_origen, "se busca por valor"),
    (_dimension_con_origen, "sin 'origen' en la FK"),
    (_dimension_dos_veces, "exactamente una columna"),
    (_tabla_sin_declarar, "no está declarada en 'staging'"),
    (_tabla_sin_uso, "declarada y sin uso"),
    (_secuencia_en_hecho, "no se admite en una tabla de tipo hecho"),
    (_mapeado_sin_miembro, "declare 'sin_mapeo'"),
    (_festivo_sin_comillas, "'etiquetas'"),
    (_toma_en_grano_atencion, "solo se declara en tablas de grano varias"),
    (_hecho_sin_filas_en_una_fuente, "el hecho necesita 'filas' en las dos fuentes"),
    (_texto_de_columna_sin_bandera, "'de' debe ser una columna del bloque con resolución 'dimension' y 'mapeado'"),
    (_texto_con_origen_propio, "solo lleva 'de: <columna>'"),
    (_orden_sin_secuencia, "'orden' solo sirve para numerar la secuencia"),
]


class TestContratoFormaCompleta:
    def test_columnas_pedidas_incluyen_clave_orden_y_bandera(self, tmp_path):
        """
        Qué es: prueba unitaria de Contrato.columnas_por_tabla con la forma completa.
        Qué hace: lee el contrato sintético y pide sus columnas en cada fuente.
        Esperado: cada tabla trae la clave de la atención; signos trae el orden de su toma; codigos trae el orden del
                  puente y la bandera de mapeo solo en el Excel (REDCap no los declara); las columnas de la dimensión
                  y del rol del puente también se piden.
        """
        # Arrange: contrato sintético válido en disco
        contrato = leer_contrato(_guardar(tmp_path, _contrato()), "doble")

        # Act: columnas por fuente
        excel = contrato.columnas_por_tabla("excel")
        redcap = contrato.columnas_por_tabla("redcap")

        # Assert: lo mínimo para unir, ordenar y resolver, sin nada de más
        assert excel == {
            "codigos": ["codigo", "fecha_codigo", "mapeado", "trauma_register_id"],
            "registro": ["genero", "llegada", "trauma_register_id"],
            "signos": ["avup", "fecha_signos", "pulso", "trauma_register_id"],
        }
        assert redcap["codigos"] == ["codigo", "trauma_register_id"]

    @pytest.mark.parametrize("defecto, fragmento", DEFECTOS, ids=[d.__name__.strip("_") for d, _ in DEFECTOS])
    def test_defecto_de_forma_referencia_o_grano_se_rechaza(self, tmp_path, defecto, fragmento):
        """
        Qué es: prueba unitaria de las reglas de leer_contrato que no leen datos (estructura, referencias y grano).
        Qué hace: introduce un defecto en el contrato sintético válido (una tabla de varias filas sin toma, un puente
                  unido a una tabla de varias filas, referencias rotas, tablas de staging sin declarar o sin uso,
                  resoluciones fuera de lugar, etiquetas booleanas, texto sin mapeo de una columna sin bandera o con
                  origen propio, orden sin secuencia, etc.) y lo lee.
        Esperado: ContratoInvalido con el mensaje de ese defecto, antes de abrir el staging o la base.
        """
        # Arrange: contrato con un defecto
        contrato = _contrato()
        defecto(contrato)
        ruta = _guardar(tmp_path, contrato)

        # Act + Assert: rechazo con el mensaje del defecto
        with pytest.raises(ContratoInvalido, match=re.escape(fragmento)):
            leer_contrato(ruta, "doble")

    def test_tipos_de_fecha_y_bandera_se_validan_contra_el_staging(self, tmp_path):
        """
        Qué es: prueba unitaria de Contrato.validar_contra para los tipos que exige cada resolución.
        Qué hace: valida el contrato sintético contra un esquema correcto y contra uno en el que la fecha de llegada y
                  la bandera de mapeo del Excel son texto.
        Esperado: el esquema correcto pasa; el otro da ContratoInvalido que nombra las dos columnas y su uso
                  (calendario y mapeado). REDCap no pide la bandera y no se ve afectado.
        """
        # Arrange: contrato válido; esquema con dos tipos incompatibles en el Excel
        contrato = leer_contrato(_guardar(tmp_path, _contrato()), "doble")
        incompatible = _esquema_valido()
        incompatible["registro"]["llegada"] = "large_string"
        incompatible["codigos"]["mapeado"] = "large_string"

        # Act + Assert: el esquema correcto pasa en las dos fuentes
        contrato.validar_contra(_esquema_valido(), "excel")
        contrato.validar_contra(_esquema_valido(), "redcap")

        # Act + Assert: los dos tipos incompatibles se reportan juntos
        with pytest.raises(ContratoInvalido) as error:
            contrato.validar_contra(incompatible, "excel")
        assert "registro.llegada" in str(error.value) and "'calendario'" in str(error.value)
        assert "codigos.mapeado" in str(error.value) and "'mapeado'" in str(error.value)


class TestContratoDelCompleto:
    def test_cubre_exactamente_las_columnas_del_ddl(self):
        """
        Qué es: prueba unitaria del contrato real del modelo completo frente a su DDL (sin base de datos).
        Qué hace: lee config/contratos/completo.yaml y compara sus tablas y columnas con los CREATE TABLE de
                  02_tables_completo.sql, sin las claves sustitutas ni el fact_id de los puentes (los resuelve el
                  Loader), y los roles del puente CIE-10 con el CHECK del DDL.
        Esperado: las mismas 24 tablas y, en cada una, las mismas columnas: ninguna columna del DDL sin entrada en el
                  contrato y ninguna entrada que el DDL no tenga.
        """
        # Arrange: DDL leído como texto
        ddl = _columnas_ddl()
        texto = DDL_COMPLETO.read_text(encoding="utf-8")
        roles_ddl = set(re.findall(r"'(\w+)'", re.search(r"rol\s+TEXT.*?CHECK \(rol IN \((.*?)\)\)", texto, re.S)
                                   .group(1)))

        # Act: columnas que declara el contrato por tabla
        contrato = leer_contrato(str(CONTRATO_COMPLETO), "completo")
        declaradas = {}
        for tabla, destino in contrato.tablas.items():
            if destino["tipo"] == "catalogo":
                declaradas[tabla] = {destino["columna"]}
            elif "por_rol" in destino:
                declaradas[tabla] = {c for b in destino["por_rol"].values() for c in b["columnas"]} | {"rol"}
            else:
                declaradas[tabla] = set(destino["columnas"])
        esperadas = {tabla: set(cols) - ({"fact_id"} if tabla.startswith("bridge_") else set())
                     for tabla, cols in ddl.items()}

        # Assert: mismas tablas, mismas columnas y mismos roles
        assert len(ddl) == 24
        assert declaradas == esperadas
        assert set(contrato.tablas["bridge_atencion_cie_10"]["por_rol"]) == roles_ddl

    def test_coincide_con_el_esquema_del_staging_y_los_tipos_del_ddl(self):
        """
        Qué es: prueba unitaria del contrato real del completo frente al esquema del staging (solo metadatos: nombres
                y tipos de Arrow en scripts/esquema_staging.csv, sin filas ni valores).
        Qué hace: valida el contrato contra el esquema de cada fuente y compara el tipo de Arrow de cada origen
                  copiado, buscado en un catálogo o guardado como texto sin mapeo con el tipo SQL de su columna
                  destino.
        Esperado: validar_contra no reporta columnas ausentes ni tipos de fecha o bandera incompatibles, y ningún
                  origen llega a una columna de tipo incompatible (texto a TEXT, enteros a INTEGER, números a NUMERIC).
                  Se omite si el CSV no existe (equipo sin staging); el Loader repite la validación en cada corrida.
        """
        # Arrange: contrato real, DDL y esquema del staging
        if not ESQUEMA_STAGING.is_file():
            pytest.skip("Falta scripts/esquema_staging.csv: ejecute scripts/esquema_staging.py")
        contrato = leer_contrato(str(CONTRATO_COMPLETO), "completo")
        ddl = _columnas_ddl()
        esquema = _esquema_staging_real()

        # Act: validación del contrato y cruce de tipos destino/origen
        for fuente in ("excel", "redcap"):
            contrato.validar_contra(esquema[fuente], fuente)
        incompatibles = []
        for nombre, _, bloque in contrato.bloques():
            tabla = nombre.split("[")[0]
            for columna, definicion in bloque["columnas"].items():
                resolucion = definicion.get("resolucion", "copia")
                origen = definicion.get("origen")
                if resolucion == "copia" and origen:
                    tipo_sql = ddl[tabla][columna]
                elif resolucion == "dimension" and origen:
                    catalogo = contrato.tablas[definicion["dimension"]]
                    tipo_sql = ddl[definicion["dimension"]][catalogo["columna"]]
                elif resolucion == "texto_sin_mapeo":
                    origen = bloque["columnas"][definicion["de"]]["origen"]
                    tipo_sql = ddl[tabla][columna]
                else:
                    continue
                for fuente, valor in origen.items():
                    if valor:
                        t, c = valor.split(".")
                        if not esquema[fuente][t][c].startswith(COMPATIBLES[tipo_sql]):
                            incompatibles.append(f"{nombre}.{columna} <- {fuente}:{valor} ({esquema[fuente][t][c]})")

        # Assert: todo origen cabe en su destino
        assert incompatibles == []
