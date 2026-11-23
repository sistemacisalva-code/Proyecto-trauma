"""
TC-CAR: CompletoLoader sobre la base de pruebas (DB_NAME_TEST), con el staging sintético de
tests/fixtures/staging_sintetico.py. Los casos con atención fija de ese generador son el resultado esperado.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
A diferencia de las pruebas del DDL, la carga confirma su transaccion: el fixture `bodega` vacia el modelo completo y
el control de cargas antes y despues de cada prueba, para que ninguna dependa de otra.
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import text

from etl.load.warehouse import por_contrato
from etl.load.warehouse.completo_loader import CompletoLoader
from etl.load.warehouse.contrato import leer_contrato
from tests.fixtures.staging_sintetico import generar_staging

RAIZ = Path(__file__).resolve().parents[3]
CONTRATO = RAIZ / "config" / "contratos" / "completo.yaml"
HOY = date(2026, 10, 27)   # fija el rango del calendario: 2011-01-01 a 2027-12-31


@pytest.fixture(scope="module")
def contrato():
    """Contrato real del modelo completo (solo el YAML versionado; no lee datos)."""
    return leer_contrato(str(CONTRATO), "completo")


@pytest.fixture
def bodega(motor_app):
    """
    Deja vacios el esquema trauma_completo y etl_control.carga (con su detalle) antes y despues de cada prueba.
    Solo toca la base de pruebas creada por bd_prueba; los datos que se cargan son sinteticos.
    """
    def vaciar():
        with motor_app.begin() as c:
            tablas = c.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'trauma_completo' AND table_type = 'BASE TABLE'"
            )).scalars().all()
            lista = ", ".join([f"trauma_completo.{t}" for t in tablas] + ["etl_control.carga"])
            c.execute(text(f"TRUNCATE {lista} RESTART IDENTITY CASCADE"))

    vaciar()
    yield motor_app
    vaciar()


def _cargar(motor, tmp_path, contrato, fuente, force=False, refresco_completo=False):
    """Genera (o regenera, igual por la semilla) el staging sintetico de la fuente y lo carga."""
    casos = generar_staging(tmp_path / "staging" / fuente, fuente, contrato)
    return casos, _cargar_carpeta(motor, tmp_path, fuente, casos.carpeta, force, refresco_completo)


def _cargar_carpeta(motor, tmp_path, fuente, carpeta, force=False, refresco_completo=False):
    """Carga el staging que ya esta en la carpeta (sin regenerarlo), por ejemplo uno que la prueba modifico."""
    loader = CompletoLoader(fuente=fuente, engine=motor, staging_dir=str(carpeta),
                            ruta_contrato=str(CONTRATO), quarantine_dir=str(tmp_path / "cuarentena"),
                            force=force, refresco_completo=refresco_completo, hoy=HOY)
    return loader.run()


def _editar_staging(carpeta, cambios: dict) -> None:
    """
    Reescribe tablas del staging sintetico conservando su esquema de Arrow y deja el manifiesto con los conteos nuevos.
    `cambios` es {tabla: funcion(DataFrame) -> DataFrame}.
    """
    for tabla, cambiar in cambios.items():
        ruta = Path(carpeta) / f"{tabla}.parquet"
        original = pq.read_table(ruta)
        nuevo = cambiar(original.to_pandas())
        pq.write_table(pa.Table.from_pandas(nuevo, schema=original.schema, preserve_index=False), ruta)
        manifiesto = Path(carpeta) / "manifiesto.json"
        datos = json.loads(manifiesto.read_text(encoding="utf-8"))
        datos["rows"][tabla] = len(nuevo)
        manifiesto.write_text(json.dumps(datos), encoding="utf-8")


def _filas(motor, sql, **parametros):
    with motor.connect() as c:
        return [tuple(f) for f in c.execute(text(sql), parametros).all()]


def _conteos(motor) -> dict[str, int]:
    """Filas de cada tabla del modelo completo."""
    tablas = [t for (t,) in _filas(motor, "SELECT table_name FROM information_schema.tables "
                                          "WHERE table_schema = 'trauma_completo' AND table_type = 'BASE TABLE'")]
    return {t: _filas(motor, f"SELECT count(*) FROM trauma_completo.{t}")[0][0] for t in tablas}


PUENTE_DE = (
    "SELECT {columnas} FROM trauma_completo.{puente} b "
    "JOIN trauma_completo.fact_trauma f ON f.fact_id = b.fact_id {joins} "
    "WHERE f.trauma_register_id = :id {filtro} ORDER BY {orden}"
)


class TestCompletoLoaderCorrida:
    @pytest.mark.parametrize("fuente", ["excel", "redcap"])
    def test_tc_car_03_y_05_reconcilia_por_uso_con_cuarentena(self, bodega, tmp_path, contrato, fuente):
        """
        Que es: prueba de integracion de la carga completa de una fuente (TC-CAR-03, TC-CAR-05).
        Que hace: carga el staging sintetico de la fuente y consulta el hecho y etl_control.
        Esperado: un hecho por atencion menos la que tiene su llegada fuera del calendario (en cuarentena, la carga
                  continua); la corrida exitosa reconcilia origen = cargadas + no usadas + cuarentena, con un detalle
                  por uso en carga_detalle; la cuarentena queda en disco.
        """
        # Arrange: bodega vacia (fixture)

        # Act
        casos, resultado = _cargar(bodega, tmp_path, contrato, fuente)

        # Assert: hechos y registro de la corrida
        hechos = {f for (f,) in _filas(bodega, "SELECT trauma_register_id FROM trauma_completo.fact_trauma")}
        assert hechos == set(casos.atenciones) - {casos.id("fuera_de_calendario")}
        totales = resultado.totales()
        assert _filas(bodega, "SELECT filas_origen, filas_cargadas, filas_no_usadas, filas_cuarentena "
                              "FROM etl_control.carga WHERE exitosa") == [tuple(totales.values())]
        assert totales["filas_origen"] == (totales["filas_cargadas"] + totales["filas_no_usadas"]
                                           + totales["filas_cuarentena"])
        assert _filas(bodega, "SELECT count(*) FROM etl_control.carga_detalle")[0][0] == len(resultado.detalle)
        assert resultado.ruta_cuarentena is not None

    def test_tc_car_01_cargar_dos_veces_deja_los_mismos_conteos(self, bodega, tmp_path, contrato):
        """
        Que es: prueba de idempotencia de la carga de REDCap (TC-CAR-01).
        Que hace: carga dos veces el mismo staging sintetico de REDCap y cuenta las filas de cada tabla.
        Esperado: los mismos conteos en todas las tablas: el reemplazo por fuente no duplica hechos ni puentes y las
                  dimensiones no crecen.
        """
        # Arrange: una primera carga
        _cargar(bodega, tmp_path, contrato, "redcap")
        antes = _conteos(bodega)

        # Act
        _cargar(bodega, tmp_path, contrato, "redcap")

        # Assert
        assert _conteos(bodega) == antes

    def test_tc_car_06_y_07_redcap_no_toca_el_excel_y_guardia(self, bodega, tmp_path, contrato):
        """
        Que es: prueba del reemplazo por fuente y de la guardia del Excel (TC-CAR-06, TC-CAR-07).
        Que hace: carga el Excel, guarda una huella de sus hechos y puentes, carga REDCap, intenta cargar el Excel
                  otra vez sin --force y luego con --force.
        Esperado: la huella del Excel no cambia al cargar REDCap; sin --force la carga se rechaza (RuntimeError); con
                  --force se reemplaza el Excel y su numero de hechos se mantiene.
        """
        # Arrange: el Excel cargado y su huella (hechos completos y filas de cada puente)
        _cargar(bodega, tmp_path, contrato, "excel")
        huella = (
            "SELECT md5(string_agg(f::text, '|' ORDER BY f.trauma_register_id)), "
            "(SELECT count(*) FROM trauma_completo.bridge_atencion_cie_10 b JOIN trauma_completo.fact_trauma x "
            " ON x.fact_id = b.fact_id WHERE x.trauma_register_id LIKE 'EX-%') "
            "FROM trauma_completo.fact_trauma f WHERE f.trauma_register_id LIKE 'EX-%'"
        )
        excel_antes = _filas(bodega, huella)
        hechos_excel = _filas(bodega, "SELECT count(*) FROM trauma_completo.fact_trauma "
                                      "WHERE trauma_register_id LIKE 'EX-%'")

        # Act + Assert: REDCap no toca el Excel
        _cargar(bodega, tmp_path, contrato, "redcap")
        assert _filas(bodega, huella) == excel_antes

        # Act + Assert: guardia del Excel
        with pytest.raises(RuntimeError, match="--force"):
            _cargar(bodega, tmp_path, contrato, "excel")
        _cargar(bodega, tmp_path, contrato, "excel", force=True)
        assert _filas(bodega, "SELECT count(*) FROM trauma_completo.fact_trauma "
                              "WHERE trauma_register_id LIKE 'EX-%'") == hechos_excel


class TestCompletoLoaderIncremental:
    def test_tc_car_20_sin_cambios_no_se_toca_ninguna_atencion(self, bodega, tmp_path, contrato):
        """
        Que es: prueba de integracion de la carga incremental sin cambios (TC-CAR-20).
        Que hace: carga dos veces el mismo staging sintetico de REDCap y compara los fact_id y los conteos de la
                  bitacora.
        Esperado: la segunda carga no cambia ningun fact_id; todas las atenciones quedan "sin cambio" (ninguna nueva,
                  modificada ni eliminada) y la bitacora lo guarda en etl_control.carga.
        """
        # Arrange: una primera carga
        _cargar(bodega, tmp_path, contrato, "redcap")
        antes = _filas(bodega, "SELECT trauma_register_id, fact_id FROM trauma_completo.fact_trauma ORDER BY 1")

        # Act
        _, resultado = _cargar(bodega, tmp_path, contrato, "redcap")

        # Assert: mismas llaves tecnicas y todo "sin cambio"
        assert _filas(bodega, "SELECT trauma_register_id, fact_id FROM trauma_completo.fact_trauma ORDER BY 1") == antes
        assert resultado.atenciones == {"nuevas": 0, "modificadas": 0, "sin_cambio": len(antes), "eliminadas": 0}
        assert _filas(bodega, "SELECT atenciones_nuevas, atenciones_modificadas, atenciones_sin_cambio, "
                              "atenciones_eliminadas FROM etl_control.carga ORDER BY id DESC LIMIT 1") == [
            (0, 0, len(antes), 0)]

    def test_tc_car_21_solo_se_reescribe_lo_que_cambio(self, bodega, tmp_path, contrato):
        """
        Que es: prueba de integracion de la carga incremental con cambios (TC-CAR-21).
        Que hace: carga REDCap, y en su staging sintetico cambia el ISS de una atencion (hecho), la descripcion de una
                  imagen de otra (solo un puente), borra una tercera y agrega una nueva; vuelve a cargar.
        Esperado: 1 nueva, 2 modificadas, 1 eliminada y el resto sin cambio; las sin cambio y las modificadas conservan
                  su fact_id (el hecho se actualiza en su lugar), la nueva recibe uno que no existia y la eliminada ya no
                  esta; el cambio solo del puente llega.
        """
        # Arrange: primera carga y el staging de la carpeta, que la prueba va a modificar
        casos, _ = _cargar(bodega, tmp_path, contrato, "redcap")
        antes = dict(_filas(bodega, "SELECT trauma_register_id, fact_id FROM trauma_completo.fact_trauma"))
        relleno = sorted((a for a in casos.atenciones if int(a.split("-")[1]) >= 13 and a in antes),
                         key=lambda a: int(a.split("-")[1]))
        cambia_hecho, se_elimina, se_copia = relleno[:3]
        con_imagenes, nueva = casos.id("imagenes"), "RC-90001"
        clave = "trauma_register_id"
        iss_antes = _filas(bodega, "SELECT iss FROM trauma_completo.fact_trauma WHERE trauma_register_id = :id",
                           id=cambia_hecho)[0][0]

        def sin_la_eliminada(df):
            return df[df[clave] != se_elimina]

        def con_la_nueva(df):
            copia = df[df[clave] == se_copia].assign(**{clave: nueva})
            return pd.concat([df, copia], ignore_index=True)

        def quitar_y_agregar(df):
            return con_la_nueva(sin_la_eliminada(df))

        def mas_iss(df):
            df.loc[df[clave] == cambia_hecho, "iss"] = df.loc[df[clave] == cambia_hecho, "iss"] + 1
            return quitar_y_agregar(df)

        def otra_descripcion(df):
            df.loc[(df[clave] == con_imagenes) & df["descripcion_imagen"].notna(), "descripcion_imagen"] = "otra descripcion"
            return quitar_y_agregar(df)

        tablas = [f.stem for f in Path(casos.carpeta).glob("*.parquet")]
        cambios = {t: quitar_y_agregar for t in tablas}
        cambios["puntuacion_de_severidad"] = mas_iss
        cambios["imagenes"] = otra_descripcion
        _editar_staging(casos.carpeta, cambios)

        # Act
        resultado = _cargar_carpeta(bodega, tmp_path, "redcap", casos.carpeta)

        # Assert: conteos
        assert resultado.atenciones == {"nuevas": 1, "modificadas": 2, "sin_cambio": len(antes) - 3, "eliminadas": 1}
        despues = dict(_filas(bodega, "SELECT trauma_register_id, fact_id FROM trauma_completo.fact_trauma"))
        assert all(despues[a] == antes[a] for a in set(antes) - {se_elimina})
        assert se_elimina not in despues and nueva in despues and despues[nueva] not in antes.values()

        # Assert: el cambio de solo el puente llego a la bodega, y el del hecho tambien
        descripciones = _filas(bodega, PUENTE_DE.format(
            columnas="b.descripcion_imagen", puente="bridge_atencion_imagen", joins="", filtro="", orden="b.secuencia"),
            id=con_imagenes)
        assert {d for (d,) in descripciones} == {"otra descripcion"}
        assert _filas(bodega, "SELECT iss FROM trauma_completo.fact_trauma WHERE trauma_register_id = :id",
                      id=cambia_hecho)[0][0] == iss_antes + 1

    def test_tc_car_22_el_refresco_completo_reescribe_todas_las_atenciones(self, bodega, tmp_path, contrato):
        """
        Que es: prueba de integracion del refresco completo (TC-CAR-22).
        Que hace: carga REDCap y la vuelve a cargar con refresco_completo=True, sin cambiar el staging.
        Esperado: todas las atenciones cuentan como modificadas y conservan su fact_id (se actualizan en su lugar);
                  los conteos de las tablas no cambian.
        """
        # Arrange
        _cargar(bodega, tmp_path, contrato, "redcap")
        antes = dict(_filas(bodega, "SELECT trauma_register_id, fact_id FROM trauma_completo.fact_trauma"))
        conteos = _conteos(bodega)

        # Act
        _, resultado = _cargar(bodega, tmp_path, contrato, "redcap", refresco_completo=True)

        # Assert
        assert resultado.atenciones == {"nuevas": 0, "modificadas": len(antes), "sin_cambio": 0, "eliminadas": 0}
        despues = dict(_filas(bodega, "SELECT trauma_register_id, fact_id FROM trauma_completo.fact_trauma"))
        assert despues == antes
        assert _conteos(bodega) == conteos

    def test_tc_car_23_una_atencion_sin_huella_cuenta_como_modificada(self, bodega, tmp_path, contrato):
        """
        Que es: prueba de integracion de las filas cargadas antes de la huella (TC-CAR-23).
        Que hace: carga REDCap, deja en NULL la huella de todas las atenciones y vuelve a cargar el mismo staging.
        Esperado: todas cuentan como modificadas y la huella queda completa (64 caracteres) en cada una.
        """
        # Arrange: una carga y sus huellas borradas, como en una bodega anterior al cambio
        _cargar(bodega, tmp_path, contrato, "redcap")
        with bodega.begin() as c:
            c.execute(text("UPDATE trauma_completo.fact_trauma SET huella = NULL"))
        total = _filas(bodega, "SELECT count(*) FROM trauma_completo.fact_trauma")[0][0]

        # Act
        _, resultado = _cargar(bodega, tmp_path, contrato, "redcap")

        # Assert
        assert resultado.atenciones["modificadas"] == total and resultado.atenciones["sin_cambio"] == 0
        assert _filas(bodega, "SELECT count(*) FROM trauma_completo.fact_trauma "
                              "WHERE huella IS NULL OR length(huella) <> 64")[0][0] == 0


class TestCompletoLoaderHecho:
    def test_tc_car_02_perfil_compartido_y_miembros_por_defecto(self, bodega, tmp_path, contrato):
        """
        Que es: prueba de las dimensiones del hecho (TC-CAR-02).
        Que hace: carga las dos fuentes y consulta el perfil de las atenciones con el mismo perfil y la atencion
                  vacia.
        Esperado: las atenciones 1 y 2 de las dos fuentes comparten una sola fila de dim_paciente; la atencion vacia
                  apunta a 'Sin dato' en el paciente y a 'No aplica' en la caida, con las medidas en NULL y sin filas
                  en ningun puente.
        """
        # Arrange: las dos fuentes cargadas
        casos_excel, _ = _cargar(bodega, tmp_path, contrato, "excel")
        casos_redcap, _ = _cargar(bodega, tmp_path, contrato, "redcap")
        compartidas = [*casos_excel.ids["perfil_compartido"], *casos_redcap.ids["perfil_compartido"]]

        # Act
        perfiles = _filas(bodega, "SELECT DISTINCT paciente_id FROM trauma_completo.fact_trauma "
                                  "WHERE trauma_register_id = ANY(:ids)", ids=compartidas)
        vacia = _filas(bodega,
                       "SELECT p.genero, c.caida, f.peso, f.fact_id FROM trauma_completo.fact_trauma f "
                       "JOIN trauma_completo.dim_paciente p ON p.paciente_id = f.paciente_id "
                       "JOIN trauma_completo.dim_caida c ON c.caida_id = f.caida_id "
                       "WHERE f.trauma_register_id = :id", id=casos_redcap.id("vacia"))

        # Assert
        assert len(perfiles) == 1
        ((genero, caida, peso, fact_id),) = vacia
        assert (genero, caida, peso) == ("Sin dato", "No aplica", None)
        puentes = ["bridge_atencion_cie_10", "bridge_atencion_lesion", "bridge_atencion_imagen",
                   "bridge_atencion_sustancia", "bridge_atencion_procedimiento", "bridge_atencion_complicacion"]
        assert all(_filas(bodega, f"SELECT count(*) FROM trauma_completo.{p} WHERE fact_id = :f", f=fact_id)[0][0] == 0
                   for p in puentes)

    @pytest.mark.parametrize("fuente", ["excel", "redcap"])
    def test_primera_toma_y_hora_truncada(self, bodega, tmp_path, contrato, fuente):
        """
        Que es: prueba de la regla de la primera toma y del truncado de la hora (TC-CAR-09).
        Que hace: carga la fuente y consulta los signos y gases de la atencion de tomas y el alta de la atencion con
                  segundos.
        Esperado: pulso 90 (se salta la toma mas temprana sin valores y la sin fecha va al final); PaO2 NULL y PaCO2
                  38, de la misma muestra; el alta 23:59:45 queda en 23:59 del 2023-03-14.
        """
        # Arrange + Act: carga de la fuente
        casos, _ = _cargar(bodega, tmp_path, contrato, fuente)

        # Act: consultas del hecho
        ((pulso, pao2, paco2),) = _filas(bodega, "SELECT frecuencia_cardiaca, pao2, paco2 "
                                                 "FROM trauma_completo.fact_trauma WHERE trauma_register_id = :id",
                                         id=casos.id("tomas"))
        alta = _filas(bodega, "SELECT h.hora, h.minuto, t.fecha FROM trauma_completo.fact_trauma f "
                              "JOIN trauma_completo.dim_horario h ON h.horario_id = f.hora_alta_id "
                              "JOIN trauma_completo.dim_tiempo t ON t.tiempo_id = f.fecha_alta_id "
                              "WHERE f.trauma_register_id = :id", id=casos.id("hora_con_segundos"))

        # Assert
        assert (float(pulso), pao2, float(paco2)) == (90.0, None, 38.0)
        assert alta == [(23, 59, date(2023, 3, 14))]


class TestCompletoLoaderPuentes:
    def test_tc_car_04_puentes_del_excel(self, bodega, tmp_path, contrato):
        """
        Que es: prueba de los puentes con el staging del Excel (TC-CAR-04).
        Que hace: carga el Excel y consulta los diagnosticos, complicaciones, sustancias y procedimientos de las
                  atenciones de cada caso, y los duplicados registrados por uso.
        Esperado: el diagnostico mapeado sin texto y los dos sin codigo con su texto_origen (la repeticion exacta se
                  une); lo mismo en complicaciones; una sola sustancia; procedimientos en orden de fecha; un duplicado
                  en cada uso de diagnostico, complicacion y sustancia.
        """
        # Arrange + Act: carga del Excel
        casos, _ = _cargar(bodega, tmp_path, contrato, "excel")
        cie = "JOIN trauma_completo.dim_cie_10 c ON c.cie_10_id = b.cie_10_id"

        # Act: filas de cada puente
        diagnosticos = _filas(bodega, PUENTE_DE.format(
            columnas="c.cie_10, b.texto_origen", puente="bridge_atencion_cie_10", joins=cie,
            filtro="AND b.rol = 'diagnostico'", orden="b.texto_origen NULLS FIRST"), id=casos.id("cie_sin_mapeo"))
        complicaciones = _filas(bodega, PUENTE_DE.format(
            columnas="c.cie_10, b.texto_origen", puente="bridge_atencion_complicacion", joins=cie, filtro="",
            orden="b.texto_origen NULLS FIRST"), id=casos.id("complicacion_sin_mapeo"))
        sustancias = _filas(bodega, PUENTE_DE.format(
            columnas="b.sustancia_id", puente="bridge_atencion_sustancia", joins="", filtro="", orden="1"),
            id=casos.id("sustancia_repetida"))
        procedimientos = _filas(bodega, PUENTE_DE.format(
            columnas="p.procedimientos, b.secuencia", puente="bridge_atencion_procedimiento",
            joins="JOIN trauma_completo.dim_procedimiento p ON p.procedimiento_id = b.procedimiento_id", filtro="",
            orden="b.secuencia"), id=casos.id("orden_procedimientos"))
        duplicados = dict(_filas(bodega, "SELECT destino, duplicado FROM etl_control.carga_detalle "
                                         "WHERE duplicado > 0"))

        # Assert
        assert diagnosticos == [("CIE SINTETICO 1", None), ("SIN CODIGO CIE-10", "texto sin pareja 1"),
                                ("SIN CODIGO CIE-10", "texto sin pareja 2")]
        assert complicaciones == [("CIE SINTETICO 2", None), ("SIN CODIGO CIE-10", "complicacion sin pareja 1"),
                                  ("SIN CODIGO CIE-10", "complicacion sin pareja 2")]
        assert len(sustancias) == 1
        assert procedimientos == [("procedimiento temprano", 1), ("procedimiento tarde", 2)]
        assert duplicados == {"bridge_atencion_cie_10[diagnostico]": 1, "bridge_atencion_complicacion": 1,
                              "bridge_atencion_sustancia": 1}

    def test_tc_car_04_puentes_de_redcap(self, bodega, tmp_path, contrato):
        """
        Que es: prueba de los puentes con el staging de REDCap (TC-CAR-04).
        Que hace: carga REDCap y consulta las lesiones y los diagnosticos de las atenciones de cada caso.
        Esperado: tres lesiones con secuencia 1 a 3, incluida la repetida exacta, y la sin mecanismo apuntando a
                  'Sin dato'; el codigo CIE-10 repetido queda una vez, sin texto_origen (REDCap no tiene bandera).
        """
        # Arrange + Act: carga de REDCap
        casos, _ = _cargar(bodega, tmp_path, contrato, "redcap")

        # Act
        lesiones = _filas(bodega, PUENTE_DE.format(
            columnas="b.secuencia, m.mecanismo_primario", puente="bridge_atencion_lesion",
            joins="JOIN trauma_completo.dim_mecanismo_primario m ON m.mecanismo_primario_id = b.mecanismo_primario_id",
            filtro="", orden="b.secuencia"), id=casos.id("lesiones"))
        diagnosticos = _filas(bodega, PUENTE_DE.format(
            columnas="c.cie_10, b.texto_origen", puente="bridge_atencion_cie_10",
            joins="JOIN trauma_completo.dim_cie_10 c ON c.cie_10_id = b.cie_10_id",
            filtro="AND b.rol = 'diagnostico'", orden="1"), id=casos.id("cie_sin_mapeo"))

        # Assert
        assert lesiones == [(1, "mecanismo_primario 1"), (2, "Sin dato"), (3, "mecanismo_primario 1")]
        assert diagnosticos == [("CIE SINTETICO 1", None)]


class TestCompletoLoaderAtomicidad:
    def test_tc_car_31_una_falla_a_mitad_de_la_carga_deja_la_bodega_como_estaba(
            self, bodega, tmp_path, contrato, monkeypatch):
        """
        Que es: prueba de integracion de la atomicidad de la carga contra PostgreSQL (TC-CAR-31).
        Que hace: carga REDCap, cambia su staging sintetico (una atencion eliminada, una nueva y una con otro ISS) y
                  vuelve a cargar con una falla simulada al insertar el primer puente, cuando el hecho ya se borro,
                  actualizo e inserto dentro de la transaccion. Despues repite la carga sin la falla.
        Esperado: la carga fallida lanza el error original; las filas de todas las tablas del modelo y el contenido
                  de los hechos (incluidos fact_id y huella) quedan iguales a antes; etl_control.carga conserva la
                  corrida exitosa y suma una fallida; la carga posterior sin falla se completa con 1 nueva, 1
                  modificada y 1 eliminada.
        """
        # Arrange: primera carga, su estado, y el staging de la carpeta con tres cambios que la segunda carga aplicaria
        casos, _ = _cargar(bodega, tmp_path, contrato, "redcap")
        ids_antes = dict(_filas(bodega, "SELECT trauma_register_id, fact_id FROM trauma_completo.fact_trauma"))
        conteos_antes = _conteos(bodega)
        hechos_antes = _filas(bodega, "SELECT md5(string_agg(f::text, '|' ORDER BY f.trauma_register_id)) "
                                      "FROM trauma_completo.fact_trauma f")
        relleno = sorted((a for a in casos.atenciones if int(a.split("-")[1]) >= 13 and a in ids_antes),
                         key=lambda a: int(a.split("-")[1]))
        cambia_hecho, se_elimina, se_copia = relleno[:3]
        clave, nueva = "trauma_register_id", "RC-90001"

        def quitar_y_agregar(df):
            copia = df[df[clave] == se_copia].assign(**{clave: nueva})
            return pd.concat([df[df[clave] != se_elimina], copia], ignore_index=True)

        def mas_iss(df):
            df.loc[df[clave] == cambia_hecho, "iss"] = df.loc[df[clave] == cambia_hecho, "iss"] + 1
            return quitar_y_agregar(df)

        cambios = {f.stem: quitar_y_agregar for f in Path(casos.carpeta).glob("*.parquet")}
        cambios["puntuacion_de_severidad"] = mas_iss
        _editar_staging(casos.carpeta, cambios)

        # La falla se simula en el primer puente: el hecho y las dimensiones ya se escribieron en la transaccion
        insertar_real = por_contrato.insertar

        def insertar_con_falla(conexion, tabla, *args, **kwargs):
            if tabla.name.startswith("bridge_"):
                raise RuntimeError("falla simulada en un puente")
            return insertar_real(conexion, tabla, *args, **kwargs)

        # Act: la carga con la falla
        with monkeypatch.context() as parche:
            parche.setattr(por_contrato, "insertar", insertar_con_falla)
            with pytest.raises(RuntimeError, match="falla simulada"):
                _cargar_carpeta(bodega, tmp_path, "redcap", casos.carpeta)

        # Assert: la bodega quedo como estaba y la corrida fallida quedo registrada aparte de la transaccion revertida
        assert _conteos(bodega) == conteos_antes
        assert _filas(bodega, "SELECT md5(string_agg(f::text, '|' ORDER BY f.trauma_register_id)) "
                              "FROM trauma_completo.fact_trauma f") == hechos_antes
        assert dict(_filas(bodega, "SELECT trauma_register_id, fact_id FROM trauma_completo.fact_trauma")) == ids_antes
        assert _filas(bodega, "SELECT exitosa FROM etl_control.carga ORDER BY id") == [(True,), (False,)]

        # Act + Assert: sin la falla, la misma carga se completa; la falla no dejo estado a medias que la bloquee
        resultado = _cargar_carpeta(bodega, tmp_path, "redcap", casos.carpeta)
        assert resultado.atenciones == {"nuevas": 1, "modificadas": 1, "sin_cambio": len(ids_antes) - 2,
                                        "eliminadas": 1}
