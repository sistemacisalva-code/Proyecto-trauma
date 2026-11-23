import json

import pandas as pd
import pytest
import yaml

from etl.load.warehouse.contrato import ContratoInvalido, leer_contrato
from etl.load.warehouse.staging import esquema_staging, leer_manifiesto, leer_tablas

RUN_ID = "2026-10-24T120000"


@pytest.fixture
def staging(tmp_path):
    """
    Crea un staging sintético de REDCap en una carpeta temporal: dos tablas pequeñas con valores inventados y su
    manifiesto. Sin datos clínicos reales y aislado del data/ del repositorio.
    """
    carpeta = tmp_path / "staging" / "redcap"
    carpeta.mkdir(parents=True)
    tablas = {
        "informacion_demografica": pd.DataFrame({"trauma_register_id": ["RC-1", "RC-2"], "edad": [30, 41],
                                                 "sexo": ["F", "M"]}),
        "imagenes": pd.DataFrame({"trauma_register_id": ["RC-1"], "tipo_imagen": ["TAC"]}),
    }
    for nombre, df in tablas.items():
        df.to_parquet(carpeta / f"{nombre}.parquet", index=False)
    (carpeta / "manifiesto.json").write_text(json.dumps({
        "run_id": RUN_ID, "source_type": "redcap", "rows": {nombre: len(df) for nombre, df in tablas.items()},
    }), encoding="utf-8")
    return carpeta


def _contrato(**cambios) -> dict:
    """Contrato sintético mínimo y válido de un modelo de prueba; `cambios` reemplaza claves de primer nivel."""
    contrato = {
        "modelo": "doble", "version": 1,
        "staging": {
            "excel": {"informacion_demografica": {"grano": "atencion"}},
            "redcap": {"informacion_demografica": {"grano": "atencion"}, "imagenes": {"grano": "varias"}},
        },
        "tablas": {
            "fact_doble": {"tipo": "hecho",
                           "filas": {"excel": "informacion_demografica", "redcap": "informacion_demografica"},
                           "columnas": {
                "trauma_register_id": {"origen": {"excel": "informacion_demografica.trauma_register_id",
                                                  "redcap": "informacion_demografica.trauma_register_id"}},
                "edad": {"origen": {"excel": "informacion_demografica.edad",
                                    "redcap": "informacion_demografica.edad"}},
                "hora_llegada": {"origen": {"excel": "informacion_demografica.hora_llegada", "redcap": None}},
            }},
            # El puente solo tiene filas en REDCap: en el Excel no pide nada
            "bridge_doble": {"tipo": "puente", "filas": {"excel": None, "redcap": "imagenes"}, "columnas": {
                "tipo_imagen": {"origen": {"excel": None, "redcap": "imagenes.tipo_imagen"}},
            }},
        },
    }
    return {**contrato, **cambios}


def _con_edad(origen) -> dict:
    """Contrato mínimo con otro `origen` en fact_doble.edad (para los defectos de una columna)."""
    contrato = _contrato()
    contrato["tablas"]["fact_doble"]["columnas"]["edad"]["origen"] = origen
    return contrato


def _guardar(tmp_path, contrato: dict) -> str:
    ruta = tmp_path / "doble.yaml"
    ruta.write_text(yaml.safe_dump(contrato, allow_unicode=True), encoding="utf-8")
    return str(ruta)


class TestStagingManifiesto:
    def test_lee_el_manifiesto_de_un_staging_coherente(self, staging):
        """
        Qué es: prueba unitaria de leer_manifiesto (caso normal).
        Qué hace: lee el manifiesto de un staging cuyas tablas coinciden con él.
        Esperado: devuelve el run_id, la fuente y las filas por tabla.
        """
        # Arrange: staging coherente del fixture

        # Act: leer el manifiesto
        manifiesto = leer_manifiesto(str(staging))

        # Assert: identifica la corrida que se va a cargar
        assert manifiesto["run_id"] == RUN_ID
        assert manifiesto["source_type"] == "redcap"
        assert manifiesto["rows"] == {"informacion_demografica": 2, "imagenes": 1}

    def test_sin_manifiesto_pide_ejecutar_la_transformacion(self, tmp_path):
        """
        Qué es: prueba unitaria de leer_manifiesto sin staging (o con un staging anterior al manifiesto).
        Qué hace: lee una carpeta que solo tiene un Parquet.
        Esperado: FileNotFoundError que indica ejecutar la transformación.
        """
        # Arrange: carpeta con una tabla y sin manifiesto
        carpeta = tmp_path / "staging" / "excel"
        carpeta.mkdir(parents=True)
        pd.DataFrame({"trauma_register_id": ["EX-1"]}).to_parquet(carpeta / "registro.parquet", index=False)

        # Act + Assert: se detiene antes de leer nada más
        with pytest.raises(FileNotFoundError, match="transformación"):
            leer_manifiesto(str(carpeta))

    @pytest.mark.parametrize("accion", ["falta_tabla", "sobra_tabla"])
    def test_tablas_distintas_al_manifiesto_se_rechazan(self, staging, accion):
        """
        Qué es: prueba unitaria de la coherencia entre el manifiesto y los Parquet del staging.
        Qué hace: borra una tabla del manifiesto o agrega una que no figura en él.
        Esperado: ValueError que nombra la tabla que falta o sobra (la foto no es de una sola corrida).
        """
        # Arrange: romper la coherencia en uno de los dos sentidos
        if accion == "falta_tabla":
            (staging / "imagenes.parquet").unlink()
        else:
            pd.DataFrame({"x": [1]}).to_parquet(staging / "ajena.parquet", index=False)

        # Act + Assert: la tabla afectada aparece en el mensaje
        with pytest.raises(ValueError, match="imagenes" if accion == "falta_tabla" else "ajena"):
            leer_manifiesto(str(staging))

    def test_filas_distintas_al_manifiesto_se_rechazan(self, staging):
        """
        Qué es: prueba unitaria del conteo de filas del manifiesto frente al de cada Parquet.
        Qué hace: reescribe una tabla con una fila más de las que declara el manifiesto.
        Esperado: ValueError con la tabla y los dos conteos; el número de filas se lee de los metadatos.
        """
        # Arrange: imagenes con 2 filas cuando el manifiesto dice 1
        pd.DataFrame({"trauma_register_id": ["RC-1", "RC-2"], "tipo_imagen": ["TAC", "RX"]}).to_parquet(
            staging / "imagenes.parquet", index=False)

        # Act + Assert: se detecta el descuadre
        with pytest.raises(ValueError, match="imagenes"):
            leer_manifiesto(str(staging))


class TestStagingLectura:
    def test_esquema_sale_de_los_metadatos_y_omite_tablas_inexistentes(self, staging):
        """
        Qué es: prueba unitaria de esquema_staging.
        Qué hace: pide el esquema de una tabla existente y de una que no existe.
        Esperado: columnas y tipos de la existente; la inexistente no aparece (la validación del contrato la reporta).
        """
        # Arrange: staging del fixture

        # Act: pedir el esquema
        esquema = esquema_staging(str(staging), ["informacion_demografica", "no_existe"])

        # Assert: solo la tabla existente, con sus tres columnas y el tipo de Arrow de la edad
        assert list(esquema) == ["informacion_demografica"]
        assert set(esquema["informacion_demografica"]) == {"trauma_register_id", "edad", "sexo"}
        assert esquema["informacion_demografica"]["edad"] == "int64"

    def test_lee_solo_las_columnas_pedidas(self, staging):
        """
        Qué es: prueba unitaria de leer_tablas (minimización de datos).
        Qué hace: pide dos columnas de informacion_demografica.
        Esperado: el DataFrame trae solo esas columnas y todas sus filas; sexo, fuera de lo pedido, no se lee.
        """
        # Arrange: staging del fixture

        # Act: leer dos columnas
        tablas = leer_tablas(str(staging), {"informacion_demografica": ["edad", "trauma_register_id"]})

        # Assert: solo lo pedido
        assert list(tablas) == ["informacion_demografica"]
        assert list(tablas["informacion_demografica"].columns) == ["edad", "trauma_register_id"]
        assert len(tablas["informacion_demografica"]) == 2


class TestContrato:
    def test_contrato_valido_agrupa_las_columnas_por_tabla_de_staging(self, tmp_path):
        """
        Qué es: prueba unitaria de leer_contrato y Contrato.columnas_por_tabla.
        Qué hace: lee un contrato sintético válido y pide sus columnas por fuente.
        Esperado: en REDCap, las columnas de cada tabla de staging sin repetir ni orígenes null, con la clave de la
                  atención en cada tabla; en el Excel, solo informacion_demografica, porque el puente no tiene filas
                  en esa fuente.
        """
        # Arrange: contrato válido en disco
        ruta = _guardar(tmp_path, _contrato())

        # Act: leer y agrupar
        contrato = leer_contrato(ruta, "doble")

        # Assert: agrupación por fuente
        assert contrato.columnas_por_tabla("redcap") == {
            "imagenes": ["tipo_imagen", "trauma_register_id"],
            "informacion_demografica": ["edad", "trauma_register_id"],
        }
        assert contrato.columnas_por_tabla("excel") == {
            "informacion_demografica": ["edad", "hora_llegada", "trauma_register_id"],
        }

    def test_validacion_contra_el_staging_nombra_todas_las_columnas_ausentes(self, tmp_path, staging):
        """
        Qué es: prueba unitaria de Contrato.validar_contra.
        Qué hace: valida el contrato del Excel contra un esquema que no tiene hora_llegada, y el de REDCap contra un
                  esquema sin la tabla imagenes.
        Esperado: ContratoInvalido que nombra cada columna ausente, no solo la primera; nada se lee del staging.
        """
        # Arrange: contrato válido y esquema del staging sintético sin imagenes
        contrato = leer_contrato(_guardar(tmp_path, _contrato()), "doble")
        esquema = esquema_staging(str(staging), ["informacion_demografica"])

        # Act + Assert: Excel sin hora_llegada
        with pytest.raises(ContratoInvalido, match="informacion_demografica.hora_llegada"):
            contrato.validar_contra(esquema, "excel")

        # Act + Assert: REDCap sin la tabla imagenes reporta sus dos columnas
        with pytest.raises(ContratoInvalido) as error:
            contrato.validar_contra(esquema, "redcap")
        assert "imagenes.tipo_imagen" in str(error.value)
        assert "imagenes.trauma_register_id" in str(error.value)

    @pytest.mark.parametrize("caso, contrato, fragmento", [
        ("otro_modelo", _contrato(modelo="mini"), "'modelo'"),
        ("sin_tablas", _contrato(tablas={}), "'tablas'"),
        ("fuente_omitida", _con_edad({"excel": "informacion_demografica.edad"}), "exactamente las fuentes"),
        ("origen_sin_tabla", _con_edad({"excel": "edad", "redcap": None}), "'tabla.columna' o null"),
    ])
    def test_estructura_invalida_se_rechaza(self, tmp_path, caso, contrato, fragmento):
        """
        Qué es: prueba unitaria de la validación de estructura del contrato.
        Qué hace: lee contratos con el modelo equivocado, sin tablas, con una fuente omitida o con un origen sin tabla.
        Esperado: ContratoInvalido con el error correspondiente; omitir una fuente no equivale a null (debe ser explícito).
        """
        # Arrange: contrato con un defecto
        ruta = _guardar(tmp_path, contrato)

        # Act + Assert: rechazo con el mensaje del defecto
        with pytest.raises(ContratoInvalido, match=fragmento):
            leer_contrato(ruta, "doble")

    def test_contrato_inexistente_se_rechaza(self, tmp_path):
        """
        Qué es: prueba unitaria de leer_contrato sin archivo.
        Qué hace: lee un contrato que no existe.
        Esperado: ContratoInvalido con el modelo y la ruta.
        """
        # Arrange: ruta inexistente
        ruta = str(tmp_path / "no_existe.yaml")

        # Act + Assert: rechazo
        with pytest.raises(ContratoInvalido, match="doble"):
            leer_contrato(ruta, "doble")
