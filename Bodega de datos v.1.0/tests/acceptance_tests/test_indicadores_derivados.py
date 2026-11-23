"""
TC-ACE-01, 08, 09, 12 y 15: indicadores del modelo completo con lógica derivada, frente a un cálculo independiente.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Usan un staging sintético propio (inventado, sin datos reales): el generador de `tests/fixtures/staging_sintetico.py` más la
siembra de `siembra.py`, que reescribe en las atenciones de relleno los valores que estos indicadores necesitan (mecanismos
presentes y ausentes, signos en los bordes de cada criterio, sangre en 0 y vacía, ISS en los bordes de cada rango, las tres
etiquetas de muerte y estancias de distinta duración). Como el staging es el de este módulo, el staging de las demás pruebas y los totales del reporte de
calidad no cambian. El valor esperado sale de leer ese staging con pandas, sin pasar por el Loader ni por el contrato.
"""
import numpy as np
import pandas as pd
import pytest

from etl.load.warehouse.contrato import CLAVE_ATENCION
from etl.load.warehouse.staging import leer_tablas
from tests.acceptance_tests.ayudas import (
    CALENDARIO, ESQUEMA, FUENTES, LLEGADA, NO_APLICA, SIN_DATO, ambas, atenciones, consulta, de_la_bodega, iguales, leer,
    promedios_iguales)
from tests.acceptance_tests.siembra import (
    COLUMNAS_DEL_MECANISMO, MECANISMOS, MUERTE, TABLA_DE_DISPOSICION, atenciones_de_relleno, sembrar)
from tests.fixtures.staging_sintetico import generar_staging

pytestmark = pytest.mark.acceptance

ATENCIONES_DE_RELLENO = 70
RANGOS_ISS = ["1-8", "9-15", "16-24", "25 o mas", "sin ISS"]


@pytest.fixture(scope="module")
def staging_dirs(contrato, tmp_path_factory):
    """
    Staging sintético sembrado de cada fuente ({fuente: carpeta}), propio de este módulo: reemplaza al de las pruebas de
    calidad, y la bodega que se carga en la base de pruebas sale de él. Determinista (semilla fija) y sin datos reales.
    """
    base = tmp_path_factory.mktemp("aceptacion_derivados")
    carpetas = {}
    for fuente in FUENTES:
        carpeta = base / "staging" / fuente
        generar_staging(carpeta, fuente, contrato, atenciones_relleno=ATENCIONES_DE_RELLENO)
        sembrar(carpeta, fuente)
        carpetas[fuente] = str(carpeta)
    return carpetas


def _mecanismos(staging_dirs: dict[str, str], universo: pd.DataFrame) -> pd.DataFrame:
    """
    Por atención del universo, qué mecanismos tiene según el staging: una columna booleana por mecanismo. Un mecanismo
    está presente si alguna de sus columnas trae valor en la primera fila de la tabla (la carga toma la primera fila de las
    hojas hijas del Excel); sin fila o sin valor, ausente.
    """
    por_fuente = []
    for fuente in FUENTES:
        marcas = {}
        for mecanismo in MECANISMOS:
            partes = []
            for tabla, columnas in COLUMNAS_DEL_MECANISMO[mecanismo][fuente]:
                df = leer_tablas(staging_dirs[fuente], {tabla: [CLAVE_ATENCION, *columnas]})[tabla]
                df = df.drop_duplicates(CLAVE_ATENCION)
                partes.append(pd.Series(df[columnas].notna().any(axis=1).to_numpy(), index=df[CLAVE_ATENCION]))
            marcas[mecanismo] = pd.concat(partes, axis=1).fillna(False).astype(bool).any(axis=1)
        por_fuente.append(pd.DataFrame(marcas))
    presentes = pd.concat(por_fuente).reindex(universo[CLAVE_ATENCION]).fillna(False).astype(bool)
    return universo.merge(presentes, left_on=CLAVE_ATENCION, right_index=True, how="left")


# Mecanismo presente en la bodega: el grupo no es la combinación 'No aplica' (grupo vacío) y, en las armas, la columna
# propia trae valor (en un grupo con datos, un atributo vacío es 'Sin dato')
MECANISMOS_EN_LA_BODEGA = f"""
    LEFT JOIN {ESQUEMA}.dim_caida c ON c.caida_id = f.caida_id
    LEFT JOIN {ESQUEMA}.dim_quemadura q ON q.quemadura_id = f.quemadura_id
    LEFT JOIN {ESQUEMA}.dim_accidente_transito a ON a.accidente_id = f.accidente_id
    LEFT JOIN {ESQUEMA}.dim_armas ar ON ar.armas_id = f.armas_id
    CROSS JOIN LATERAL (VALUES
        ('caida', c.caida <> '{NO_APLICA}'),
        ('quemadura', q.quemadura <> '{NO_APLICA}'),
        ('accidente', a.velocidad_colision <> '{NO_APLICA}'),
        ('arma_fuego', ar.lesion_arma_fuego NOT IN ('{NO_APLICA}', '{SIN_DATO}')),
        ('arma_blanca', ar.lesion_arma_blanca NOT IN ('{NO_APLICA}', '{SIN_DATO}'))
    ) AS m (mecanismo, presente)"""


def _rango_iss(iss: pd.Series) -> pd.Series:
    """Los mismos cortes de TC-ACE-07 escritos con numpy; un ISS vacío o menor que 1 queda 'sin ISS'."""
    return pd.Series(np.select([iss.between(1, 8), iss.between(9, 15), iss.between(16, 24), iss >= 25],
                               RANGOS_ISS[:4], default="sin ISS"), index=iss.index)


class TestIndicadoresPorMecanismo:
    def test_tc_ace_01_casos_por_mes_de_admision_y_mecanismo(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de los casos por mes de admisión y mecanismo (fact_trauma, dim_tiempo, dim_caida,
                dim_quemadura, dim_accidente_transito, dim_armas).
        Que hace: cuenta las atenciones por año, mes de llegada y mecanismo (caída, quemadura, accidente de tránsito,
                  arma de fuego y arma blanca) en la bodega y en el staging; una atención cuenta en cada mecanismo que tenga.
        Esperado: conteo idéntico por año, mes y mecanismo (diferencia 0); hay atenciones sin ningún mecanismo (apuntan a
                  'No aplica' y no cuentan) y atenciones con dos, que suman en cada uno.
        """
        # Arrange: las llegadas del staging y los mecanismos que trae cada atención; sin llegada no hay mes
        universo = atenciones(staging_dirs)
        llegadas = de_la_bodega(leer(staging_dirs, ambas("informacion_demografica", {LLEGADA: "llegada"})), universo)
        base = llegadas.dropna(subset=["llegada"]).merge(_mecanismos(staging_dirs, universo), on=CLAVE_ATENCION)
        largo = base.melt(id_vars=["llegada"], value_vars=list(MECANISMOS), var_name="mecanismo", value_name="tiene")
        largo = largo[largo["tiene"]]
        esperado = largo.groupby([largo["llegada"].dt.year.astype("int64").rename("anio"),
                                  largo["llegada"].dt.month.astype("int64").rename("mes"), "mecanismo"]).size()

        # Act
        obtenido = consulta(conexion, f"""
            SELECT t.anio::bigint AS anio, t.mes::bigint AS mes, m.mecanismo, count(*) AS n
            FROM {ESQUEMA}.fact_trauma f JOIN {ESQUEMA}.dim_tiempo t ON t.tiempo_id = f.fecha_admision_id
            {MECANISMOS_EN_LA_BODEGA}
            WHERE m.presente GROUP BY 1, 2, 3""").set_index(["anio", "mes", "mecanismo"])["n"]

        # Assert: la siembra produjo los casos que ejercitan el indicador, y los conteos coinciden
        por_atencion = base[list(MECANISMOS)].sum(axis=1)
        assert (por_atencion == 0).any(), "el staging debe tener atenciones sin ningún mecanismo"
        assert (por_atencion >= 2).any(), "el staging debe tener atenciones con dos mecanismos"
        assert set(esperado.index.get_level_values("mecanismo")) == set(MECANISMOS), "falta algún mecanismo"
        iguales(esperado, obtenido)


class TestIndicadoresDeGravedad:
    def test_tc_ace_08_pacientes_criticos_por_gcs_presion_sistolica_e_indice_de_choque(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de los pacientes críticos (fact_trauma).
        Que hace: cuenta las atenciones con GCS menor de 9 (suma de los tres componentes), presión sistólica menor de 90 e
                  índice de choque (frecuencia cardiaca / presión sistólica) mayor de 0,9, en la bodega y en el staging,
                  sobre las atenciones sembradas con valores en los bordes de cada criterio.
        Esperado: los tres conteos iguales a los del staging; con un componente del GCS o un signo vacío el criterio
                  queda indeterminado y no cuenta; con presión sistólica 0 el índice no se calcula (sin dividir por cero).
        """
        # Arrange: solo las atenciones sembradas, cuya primera toma de signos es la misma en todas sus filas
        sembradas = atenciones_de_relleno(staging_dirs["excel"]) + atenciones_de_relleno(staging_dirs["redcap"])
        signos = leer(staging_dirs, ambas("signos_vitales", {
            "gcs_ocular": "ocular", "gcs_verbal": "verbal", "gcs_motora": "motor",
            "presion_arterial_sistolica": "sistolica", "frecuencia_cardiaca": "frecuencia"}))
        signos = de_la_bodega(signos, atenciones(staging_dirs)).drop_duplicates(CLAVE_ATENCION)
        signos = signos[signos[CLAVE_ATENCION].isin(sembradas)]
        gcs = signos["ocular"] + signos["verbal"] + signos["motor"]
        indice = signos["frecuencia"] / signos["sistolica"].replace(0, np.nan)
        esperado = {"gcs": int((gcs < 9).sum()), "sistolica": int((signos["sistolica"] < 90).sum()),
                    "choque": int((indice > 0.9).sum())}

        # Act: el mismo conjunto de atenciones en la bodega; con un NULL o una división entre NULL no hay criterio
        lista = ", ".join(f"'{llave}'" for llave in sembradas)
        obtenido = consulta(conexion, f"""
            SELECT count(*) FILTER (WHERE gcs_ocular + gcs_verbal + gcs_motor < 9) AS gcs,
                   count(*) FILTER (WHERE presion_sistolica < 90) AS sistolica,
                   count(*) FILTER (WHERE frecuencia_cardiaca / NULLIF(presion_sistolica, 0) > 0.9) AS choque
            FROM {ESQUEMA}.fact_trauma WHERE trauma_register_id IN ({lista})""").iloc[0].astype("int64").to_dict()

        # Assert: cada criterio tiene casos que cuentan y casos que no, entre ellos los indeterminados
        assert gcs.isna().any() and signos["sistolica"].isna().any() and signos["frecuencia"].isna().any()
        assert (signos["sistolica"] == 0).any(), "debe haber una presión sistólica 0 (sin división por cero)"
        assert all(0 < n < len(signos) for n in esperado.values()), f"cada criterio debe separar casos: {esperado}"
        assert obtenido == esperado

    def test_tc_ace_09_mortalidad_por_rango_de_iss_y_por_mecanismo(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de la mortalidad por rango de ISS y por mecanismo (fact_trauma, dim_desenlace y las
                dimensiones del mecanismo).
        Que hace: calcula, por rango de ISS y por mecanismo, las muertes (las tres etiquetas de muerte de
                  disposicion_paciente), los casos con disposición registrada y la tasa, en la bodega y en el staging.
        Esperado: mismos grupos y tasa igual al cálculo independiente (diferencia menor a 0,01 puntos porcentuales); el
                  denominador son los casos con disposición registrada, no todos.
        """
        # Arrange: ISS, disposición y mecanismos de cada atención del universo; una disposición vacía no entra al denominador
        universo = atenciones(staging_dirs)
        columna = {"disposicion_o_destino_del_paciente": "disposicion"}
        disposicion = leer(staging_dirs, {f: (TABLA_DE_DISPOSICION[f], columna) for f in FUENTES})
        iss = leer(staging_dirs, ambas("puntuacion_de_severidad", {"iss": "iss"}))
        base = (universo.merge(disposicion, on=CLAVE_ATENCION, how="left").merge(iss, on=CLAVE_ATENCION, how="left")
                .merge(_mecanismos(staging_dirs, universo), on=CLAVE_ATENCION))
        base = base.assign(rango=_rango_iss(base["iss"]), registrada=base["disposicion"].notna(),
                           muerte=base["disposicion"].isin(MUERTE))

        def tasas(grupos: pd.DataFrame, nombre: str) -> pd.DataFrame:
            resumen = grupos.groupby(nombre).agg(muertes=("muerte", "sum"), con_disposicion=("registrada", "sum"))
            resumen["tasa"] = 100 * resumen["muertes"] / resumen["con_disposicion"].replace(0, np.nan)
            return resumen.reset_index().astype({"muertes": "int64", "con_disposicion": "int64"})

        largo = base.melt(id_vars=["muerte", "registrada"], value_vars=list(MECANISMOS), var_name="mecanismo",
                          value_name="tiene")
        esperado_iss, esperado_mecanismo = tasas(base, "rango"), tasas(largo[largo["tiene"]], "mecanismo")

        # Act: la misma tasa en SQL; sin casos con disposición la tasa queda NULL (sin dividir por cero)
        muertes_sql = ", ".join(f"'{etiqueta}'" for etiqueta in MUERTE)
        medidas = f"""
            count(*) FILTER (WHERE d.disposicion_paciente IN ({muertes_sql})) AS muertes,
            count(*) FILTER (WHERE d.disposicion_paciente <> '{SIN_DATO}') AS con_disposicion,
            (100.0 * count(*) FILTER (WHERE d.disposicion_paciente IN ({muertes_sql}))
                / NULLIF(count(*) FILTER (WHERE d.disposicion_paciente <> '{SIN_DATO}'), 0))::float AS tasa"""
        obtenido_iss = consulta(conexion, f"""
            SELECT CASE WHEN f.iss BETWEEN 1 AND 8 THEN '1-8' WHEN f.iss BETWEEN 9 AND 15 THEN '9-15'
                        WHEN f.iss BETWEEN 16 AND 24 THEN '16-24' WHEN f.iss >= 25 THEN '25 o mas' ELSE 'sin ISS' END AS rango,
                   {medidas}
            FROM {ESQUEMA}.fact_trauma f JOIN {ESQUEMA}.dim_desenlace d ON d.desenlace_id = f.desenlace_id GROUP BY 1""")
        obtenido_mecanismo = consulta(conexion, f"""
            SELECT m.mecanismo, {medidas}
            FROM {ESQUEMA}.fact_trauma f JOIN {ESQUEMA}.dim_desenlace d ON d.desenlace_id = f.desenlace_id
            {MECANISMOS_EN_LA_BODEGA} WHERE m.presente GROUP BY 1""")

        # Assert: la siembra produjo muertes de las tres etiquetas, casos sin disposición y varios rangos con muertes
        registradas = set(disposicion["disposicion"].dropna())
        assert set(MUERTE) <= registradas, "el staging debe traer las tres etiquetas de muerte"
        assert esperado_iss["con_disposicion"].sum() < len(base), "debe haber casos sin disposición registrada"
        assert (esperado_iss["muertes"] > 0).sum() >= 2 and (esperado_mecanismo["muertes"] > 0).sum() >= 2
        promedios_iguales(esperado_iss, obtenido_iss, ["rango"])
        promedios_iguales(esperado_mecanismo, obtenido_mecanismo, ["mecanismo"])


class TestIndicadoresDeRecursos:
    def test_tc_ace_12_atenciones_transfundidas_y_litros_totales(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de las atenciones transfundidas y los litros de sangre (fact_trauma).
        Que hace: cuenta las atenciones con sangre mayor que 0 y suma los litros en la bodega y en el staging, y cuenta
                  aparte las de sangre en 0 y las de sangre vacía.
        Esperado: conteo exacto y diferencia de litros menor a 0,01; el 0 no es transfundido ni se convierte en vacío, y el
                  vacío (sin datos) no cuenta como transfundido.
        """
        # Arrange: líquidos tiene una fila por atención; el vacío no suma y no es 0
        sangre = de_la_bodega(leer(staging_dirs, ambas("liquidos", {"sangre": "sangre"})), atenciones(staging_dirs))["sangre"]
        esperado = {"transfundidas": int((sangre > 0).sum()), "litros": float(sangre.sum()),
                    "en_cero": int((sangre == 0).sum()), "vacias": int(sangre.isna().sum())}

        # Act
        obtenido = consulta(conexion, f"""
            SELECT count(*) FILTER (WHERE sangre_l > 0) AS transfundidas,
                   COALESCE(sum(sangre_l), 0)::float AS litros,
                   count(*) FILTER (WHERE sangre_l = 0) AS en_cero,
                   count(*) FILTER (WHERE sangre_l IS NULL) AS vacias
            FROM {ESQUEMA}.fact_trauma""").iloc[0].to_dict()

        # Assert: hay sangre en 0 y vacía en el staging, y la carga no confunde una con la otra
        assert esperado["en_cero"] > 0 and esperado["vacias"] > 0, "la siembra debe dejar sangre en 0 y vacía"
        assert {k: int(obtenido[k]) for k in ("transfundidas", "en_cero", "vacias")} == {
            k: esperado[k] for k in ("transfundidas", "en_cero", "vacias")}
        assert abs(obtenido["litros"] - esperado["litros"]) < 0.01


class TestIndicadoresDeEstancia:
    def test_tc_ace_15_promedio_de_dias_entre_admision_y_alta_por_mes_de_admision(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación del promedio de días entre la fecha de admisión y la de alta, por mes de admisión
                (fact_trauma y dim_tiempo, en sus relaciones de admisión y de alta).
        Que hace: calcula, por año y mes de admisión, el promedio de días enteros entre las dos fechas y cuántas atenciones
                  entran al promedio, en la bodega (resta de dos fechas de dim_tiempo) y en el staging (resta de fechas en
                  pandas), sobre atenciones sembradas con estancias de 0 a 30 días, con el alta a las 23:50 y a las 00:10, y
                  algunas sin alta.
        Esperado: mismos meses, mismo número de atenciones y promedio igual al cálculo independiente (diferencia menor a
                  0,01); solo cuentan las atenciones con las dos fechas y el cálculo es en días enteros (el hecho no guarda
                  la hora de admisión): un alta a las 00:10 del día siguiente suma 1 día aunque hayan pasado minutos.
        """
        # Arrange: las dos fechas de cada atención de la bodega; sin alta o sin llegada no hay estancia, y un alta fuera del
        # calendario manda la atención a cuarentena (no está en la bodega)
        universo = atenciones(staging_dirs)
        llegadas = leer(staging_dirs, ambas("informacion_demografica", {LLEGADA: "llegada"}))
        altas = leer(staging_dirs, ambas("hospitalizacion", {"fecha_y_hora_de_alta": "alta"})).drop_duplicates(CLAVE_ATENCION)
        base = de_la_bodega(llegadas, universo).merge(altas, on=CLAVE_ATENCION, how="left")
        en_calendario = base["alta"].isna() | ((base["alta"] >= CALENDARIO[0]) & (base["alta"] < CALENDARIO[1]))
        base = base[en_calendario]
        con_ambas = base.dropna(subset=["llegada", "alta"]).copy()
        con_ambas["dias"] = (con_ambas["alta"].dt.normalize() - con_ambas["llegada"].dt.normalize()).dt.days
        esperado = (con_ambas.groupby([con_ambas["llegada"].dt.year.astype("int64").rename("anio"),
                                       con_ambas["llegada"].dt.month.astype("int64").rename("mes")])
                    .agg(promedio=("dias", "mean"), atenciones=("dias", "size")).reset_index())

        # Act: la misma resta en la bodega; con una de las dos fechas vacía la atención no entra al promedio
        obtenido = consulta(conexion, f"""
            SELECT t.anio::bigint AS anio, t.mes::bigint AS mes, avg(a.fecha - t.fecha)::float AS promedio,
                   count(*)::bigint AS atenciones
            FROM {ESQUEMA}.fact_trauma f
            JOIN {ESQUEMA}.dim_tiempo t ON t.tiempo_id = f.fecha_admision_id
            JOIN {ESQUEMA}.dim_tiempo a ON a.tiempo_id = f.fecha_alta_id
            GROUP BY 1, 2""")

        # Assert: la siembra produjo atenciones sin alta y estancias distintas, y el cálculo coincide
        assert base["alta"].isna().any(), "debe haber atenciones sin alta (no entran al promedio)"
        assert con_ambas["dias"].nunique() > 3, "las estancias sembradas deben ser de duración distinta"
        menos_de_un_dia = (con_ambas["alta"] - con_ambas["llegada"]) < pd.Timedelta(days=1)
        assert (menos_de_un_dia & (con_ambas["dias"] >= 1)).any(), (
            "debe haber una estancia de menos de 24 horas que cuente como 1 día (alta a las 00:10 del día siguiente)")
        assert len(esperado) > 1, "debe haber más de un mes de admisión"
        promedios_iguales(esperado, obtenido, ["anio", "mes"])
