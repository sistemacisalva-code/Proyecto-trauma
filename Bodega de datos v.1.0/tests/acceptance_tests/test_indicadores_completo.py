"""
TC-ACE-02, 03, 04, 05, 06, 07, 10, 11, 13 y 14: indicadores del modelo completo frente a un cálculo independiente.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
La bodega se carga una vez por módulo con el staging sintético (inventado, sin datos reales) en la base de pruebas; el
valor esperado sale de leer ese mismo staging con pandas, sin pasar por el Loader ni por el contrato de carga.
"""
import numpy as np
import pandas as pd
import pytest

from etl.load.warehouse.contrato import CLAVE_ATENCION
from tests.acceptance_tests.ayudas import (
    ESQUEMA, SIN_CODIGO, SIN_DATO, ambas, atenciones, consulta, de_la_bodega, iguales, leer, promedios_iguales)

pytestmark = pytest.mark.acceptance


class TestIndicadoresDemograficosYDeEstancia:
    def test_tc_ace_02_porcentaje_de_casos_por_quinquenio_y_genero(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación del indicador de casos por quinquenio de edad y género (fact_trauma, dim_paciente).
        Que hace: cuenta las atenciones por quinquenio y género en la bodega y en el staging, y calcula el porcentaje.
        Esperado: conteo idéntico por grupo (diferencia 0) y porcentajes que suman 100 %.
        """
        # Arrange: el cálculo independiente agrupa la demografía del staging; el vacío se lee como 'Sin dato'
        base = atenciones(staging_dirs, quinquenio="quinquenio_edad", genero="genero").fillna(SIN_DATO)
        esperado = base.groupby(["quinquenio", "genero"]).size()

        # Act
        obtenido = consulta(conexion, f"""
            SELECT p.quinquenio, p.genero, count(*) AS n FROM {ESQUEMA}.fact_trauma f
            JOIN {ESQUEMA}.dim_paciente p USING (paciente_id) GROUP BY 1, 2""").set_index(["quinquenio", "genero"])["n"]

        # Assert: los conteos coinciden y, como el porcentaje es conteo / total, también suma 100
        iguales(esperado, obtenido)
        assert np.isclose((obtenido / obtenido.sum() * 100).sum(), 100.0)
        assert obtenido.sum() == len(base)

    def test_tc_ace_03_promedio_de_dias_de_hospitalizacion_y_uci_por_mes_de_alta(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación del promedio de días de hospitalización y de UCI por mes de alta (fact_trauma,
                dim_tiempo).
        Que hace: promedia ambas medidas por año y mes de alta en la bodega y en el staging.
        Esperado: mismos meses y diferencia menor a 0,01 en cada promedio; las atenciones sin alta no cuentan.
        """
        # Arrange: hospitalización y UCI se unen por atención; AVG y mean() ignoran los vacíos
        universo = atenciones(staging_dirs)
        hospitalizacion = leer(staging_dirs, ambas("hospitalizacion", {
            "fecha_y_hora_de_alta": "alta", "dias_de_hospitalizacion": "dias_hospitalizacion"}))
        uci = leer(staging_dirs, ambas("uci", {"dias_usados_uci": "uci_dias"}))
        base = de_la_bodega(hospitalizacion, universo).merge(uci, on=CLAVE_ATENCION, how="left")
        base = base[base["alta"].notna()]
        esperado = (base.groupby([base["alta"].dt.year.astype("int64").rename("anio"),
                                  base["alta"].dt.month.astype("int64").rename("mes")])
                    [["dias_hospitalizacion", "uci_dias"]].mean().reset_index())

        # Act
        obtenido = consulta(conexion, f"""
            SELECT t.anio::bigint AS anio, t.mes::bigint AS mes,
                   avg(f.dias_hospitalizacion)::float AS dias_hospitalizacion, avg(f.uci_dias)::float AS uci_dias
            FROM {ESQUEMA}.fact_trauma f JOIN {ESQUEMA}.dim_tiempo t ON t.tiempo_id = f.fecha_alta_id
            GROUP BY 1, 2""")

        # Assert
        assert len(esperado) > 1, "el staging sintético debe tener altas en más de un mes"
        promedios_iguales(esperado, obtenido, ["anio", "mes"])

    def test_tc_ace_04_porcentaje_de_casos_por_disposicion_del_paciente(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación del porcentaje de casos por disposición del paciente (fact_trauma, dim_desenlace).
        Que hace: cuenta las atenciones por disposición en la bodega y en el staging (el Excel la trae de
                  atencion_urgencias y REDCap de hospitalizacion).
        Esperado: conteo idéntico por disposición, porcentajes que suman 100 % y una disposición por cada atención.
        """
        # Arrange: cada fuente tiene la disposición en una tabla distinta; el vacío se lee como 'Sin dato'
        universo = atenciones(staging_dirs)
        columna = {"disposicion_o_destino_del_paciente": "disposicion"}
        disposicion = leer(staging_dirs, {"excel": ("atencion_urgencias", columna), "redcap": ("hospitalizacion", columna)})
        esperado = de_la_bodega(disposicion, universo).fillna(SIN_DATO).groupby("disposicion").size()

        # Act
        obtenido = consulta(conexion, f"""
            SELECT d.disposicion_paciente AS disposicion, count(*) AS n FROM {ESQUEMA}.fact_trauma f
            JOIN {ESQUEMA}.dim_desenlace d USING (desenlace_id) GROUP BY 1""").set_index("disposicion")["n"]

        # Assert
        iguales(esperado, obtenido)
        assert np.isclose((obtenido / obtenido.sum() * 100).sum(), 100.0)
        assert obtenido.sum() == len(universo)


class TestIndicadoresClinicos:
    def test_tc_ace_05_diagnosticos_cie_10_mas_frecuentes(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de los diagnósticos CIE-10 más frecuentes (bridge_atencion_cie_10, dim_cie_10).
        Que hace: cuenta las atenciones distintas por código en el rol diagnóstico, en la bodega y en el staging. Lo
                  no mapeado se agrupa en 'SIN CODIGO CIE-10', y una atención con ese código dos veces cuenta una.
        Esperado: conteo idéntico por código (diferencia 0), con el caso de textos sin mapear incluido.
        """
        # Arrange: el Excel marca con cie10_mapeado lo que tiene código; REDCap trae solo códigos
        diagnosticos = leer(staging_dirs, {
            "excel": ("cie_10_diagnostico_definitivo", {"cie_10_diagnostico_definitivo": "codigo", "cie10_mapeado": "mapeado"}),
            "redcap": ("cie_10_diagnosticos", {"cie_10_diagnostico_definitivo": "codigo"})})
        diagnosticos = de_la_bodega(diagnosticos, atenciones(staging_dirs))
        diagnosticos = diagnosticos[diagnosticos["codigo"].notna()].copy()
        diagnosticos.loc[diagnosticos["mapeado"].eq(False), "codigo"] = SIN_CODIGO
        esperado = diagnosticos.drop_duplicates([CLAVE_ATENCION, "codigo"]).groupby("codigo").size()

        # Act
        obtenido = consulta(conexion, f"""
            SELECT c.cie_10 AS codigo, count(DISTINCT b.fact_id) AS n FROM {ESQUEMA}.bridge_atencion_cie_10 b
            JOIN {ESQUEMA}.dim_cie_10 c USING (cie_10_id) WHERE b.rol = 'diagnostico' GROUP BY 1""").set_index("codigo")["n"]

        # Assert
        assert SIN_CODIGO in esperado.index, "el staging sintético debe tener diagnósticos sin mapear"
        iguales(esperado, obtenido)

    def test_tc_ace_07_casos_por_rango_de_iss(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de los casos por rango de ISS (fact_trauma).
        Que hace: clasifica el ISS en 1-8, 9-15, 16-24 y 25 o más (un ISS vacío o menor que 1 queda 'sin ISS') y
                  cuenta las atenciones por rango en la bodega y en el staging.
        Esperado: conteo idéntico por rango y los rangos más los casos sin ISS suman el total de atenciones.
        """
        # Arrange: los mismos cortes escritos con numpy; el borde del último rango (25 inclusive) está por confirmar
        iss = de_la_bodega(leer(staging_dirs, ambas("puntuacion_de_severidad", {"iss": "iss"})), atenciones(staging_dirs))["iss"]
        rangos = np.select([iss.between(1, 8), iss.between(9, 15), iss.between(16, 24), iss >= 25],
                           ["1-8", "9-15", "16-24", "25 o mas"], default="sin ISS")
        esperado = pd.Series(rangos).value_counts()

        # Act
        obtenido = consulta(conexion, f"""
            SELECT CASE WHEN iss BETWEEN 1 AND 8 THEN '1-8' WHEN iss BETWEEN 9 AND 15 THEN '9-15'
                        WHEN iss BETWEEN 16 AND 24 THEN '16-24' WHEN iss >= 25 THEN '25 o mas' ELSE 'sin ISS' END AS rango,
                   count(*) AS n FROM {ESQUEMA}.fact_trauma GROUP BY 1""").set_index("rango")["n"]

        # Assert
        iguales(esperado, obtenido)
        assert obtenido.sum() == len(iss)

    def test_tc_ace_10_atenciones_con_uci_y_con_procedimientos(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de las atenciones con UCI y con al menos un procedimiento (fact_trauma,
                bridge_atencion_procedimiento).
        Que hace: cuenta las atenciones con uci_dias mayor que 0 y las atenciones distintas con filas en el puente.
        Esperado: ambos conteos iguales al del staging; el segundo cuenta atenciones, no filas del puente (hay una
                  atención con dos procedimientos).
        """
        # Arrange: la fila huérfana del staging no pertenece a ninguna atención de la bodega y no cuenta
        universo = atenciones(staging_dirs)
        uci = de_la_bodega(leer(staging_dirs, ambas("uci", {"dias_usados_uci": "uci_dias"})), universo)
        procedimientos = leer(staging_dirs, ambas("procedimientos", {
            "procedimientos": "procedimiento", "fecha_y_hora_de_procedimiento": "fecha", "duracion_procedimiento_seg": "duracion"}))
        procedimientos = de_la_bodega(procedimientos, universo)
        con_valor = procedimientos[procedimientos[["procedimiento", "fecha", "duracion"]].notna().any(axis=1)]

        # Act
        con_uci = consulta(conexion, f"SELECT count(*) AS n FROM {ESQUEMA}.fact_trauma WHERE uci_dias > 0")["n"][0]
        puente = consulta(conexion, f"""
            SELECT count(DISTINCT fact_id) AS atenciones, count(*) AS filas
            FROM {ESQUEMA}.bridge_atencion_procedimiento""")

        # Assert
        assert con_uci == (uci["uci_dias"] > 0).sum()
        assert puente["atenciones"][0] == con_valor[CLAVE_ATENCION].nunique()
        assert puente["filas"][0] > puente["atenciones"][0], "debe haber una atención con varios procedimientos"

    def test_tc_ace_11_atenciones_por_parte_del_cuerpo_lesionada(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de las atenciones por parte del cuerpo lesionada (bridge_atencion_lesion,
                dim_parte_cuerpo_lesion).
        Que hace: cuenta las atenciones distintas por parte del cuerpo en la bodega y en el staging (el Excel las trae
                  de tipo_violencia y REDCap de examen_fisico).
        Esperado: conteo idéntico por parte (diferencia 0); dos lesiones iguales en una atención cuentan una vez.
        """
        # Arrange: una lesión es una fila con parte del cuerpo o tipo de lesión; sin parte se lee como 'Sin dato'
        columnas = {"parte_del_cuerpo": "parte", "tipo_de_lesion": "tipo"}
        lesiones = leer(staging_dirs, {"excel": ("tipo_violencia", columnas), "redcap": ("examen_fisico", columnas)})
        lesiones = de_la_bodega(lesiones, atenciones(staging_dirs))
        lesiones = lesiones[lesiones[["parte", "tipo"]].notna().any(axis=1)].assign(
            parte=lambda d: d["parte"].fillna(SIN_DATO))
        esperado = lesiones.drop_duplicates([CLAVE_ATENCION, "parte"]).groupby("parte").size()

        # Act
        obtenido = consulta(conexion, f"""
            SELECT p.parte_cuerpo AS parte, count(DISTINCT b.fact_id) AS n FROM {ESQUEMA}.bridge_atencion_lesion b
            JOIN {ESQUEMA}.dim_parte_cuerpo_lesion p USING (parte_cuerpo_lesion_id) GROUP BY 1""").set_index("parte")["n"]
        filas = consulta(conexion, f"SELECT count(*) AS n FROM {ESQUEMA}.bridge_atencion_lesion")["n"][0]

        # Assert: contar filas del puente en vez de atenciones daría más que la suma por parte
        iguales(esperado, obtenido)
        assert filas > obtenido.sum(), "debe haber una atención con la misma parte lesionada dos veces"

    def test_tc_ace_13_atenciones_con_imagenes_por_tipo_de_imagen(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de las atenciones con al menos una imagen, por tipo (bridge_atencion_imagen,
                dim_imagen).
        Que hace: cuenta las atenciones distintas por tipo de imagen en la bodega y en el staging.
        Esperado: conteo idéntico por tipo (diferencia 0); una atención con dos imágenes del mismo tipo cuenta una
                  vez y la imagen sin ningún valor no cuenta.
        """
        # Arrange: una imagen es una fila con tipo, región o descripción; sin tipo se lee como 'Sin dato'
        imagenes = leer(staging_dirs, ambas("imagenes", {
            "tipo_de_imagen": "tipo", "parte_del_cuerpo_imagenes": "region", "descripcion_imagen": "descripcion"}))
        imagenes = de_la_bodega(imagenes, atenciones(staging_dirs))
        imagenes = imagenes[imagenes[["tipo", "region", "descripcion"]].notna().any(axis=1)].assign(
            tipo=lambda d: d["tipo"].fillna(SIN_DATO))
        esperado = imagenes.drop_duplicates([CLAVE_ATENCION, "tipo"]).groupby("tipo").size()

        # Act
        obtenido = consulta(conexion, f"""
            SELECT COALESCE(i.tipo_imagen, '{SIN_DATO}') AS tipo, count(DISTINCT b.fact_id) AS n
            FROM {ESQUEMA}.bridge_atencion_imagen b JOIN {ESQUEMA}.dim_imagen i USING (imagen_id) GROUP BY 1""").set_index("tipo")["n"]
        filas = consulta(conexion, f"SELECT count(*) AS n FROM {ESQUEMA}.bridge_atencion_imagen")["n"][0]

        # Assert
        iguales(esperado, obtenido)
        assert filas > obtenido.sum(), "debe haber una atención con dos imágenes del mismo tipo"

    def test_tc_ace_14_prevalencia_por_sustancia_de_abuso(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de la prevalencia por sustancia de abuso (bridge_atencion_sustancia,
                dim_sustancia).
        Que hace: cuenta las atenciones distintas por sustancia en la bodega y en el staging (el Excel la trae de
                  abuso_sustancias y REDCap de motivo_de_consulta).
        Esperado: conteo idéntico por sustancia (diferencia 0); la sustancia repetida en una atención cuenta una vez.
        """
        # Arrange: cada fuente tiene la sustancia en una tabla distinta; el vacío no es una sustancia
        columna = {"abuso_de_drogas": "sustancia"}
        sustancias = leer(staging_dirs, {"excel": ("abuso_sustancias", columna), "redcap": ("motivo_de_consulta", columna)})
        sustancias = de_la_bodega(sustancias, atenciones(staging_dirs)).dropna(subset=["sustancia"])
        esperado = sustancias.drop_duplicates([CLAVE_ATENCION, "sustancia"]).groupby("sustancia").size()

        # Act
        obtenido = consulta(conexion, f"""
            SELECT s.sustancia, count(DISTINCT b.fact_id) AS n FROM {ESQUEMA}.bridge_atencion_sustancia b
            JOIN {ESQUEMA}.dim_sustancia s USING (sustancia_id) GROUP BY 1""").set_index("sustancia")["n"]

        # Assert
        iguales(esperado, obtenido)


class TestIndicadoresDeHorario:
    def test_tc_ace_06_casos_por_franja_horaria_de_alta(self, conexion, staging_dirs):
        """
        Que es: prueba de aceptación de los casos por franja horaria de alta (fact_trauma, dim_horario).
        Que hace: cuenta las atenciones por franja de una hora ('HH:00 - HH:00') en la bodega y en el staging.
        Esperado: conteo idéntico por franja, con el alta a las 23:59:45 en '23:00 - 00:00' (hora truncada al minuto,
                  mismo día) y las atenciones sin alta fuera del conteo.
        """
        # Arrange: la franja sale de la hora del alta; truncar o no los segundos no la cambia, redondear sí
        alta = leer(staging_dirs, ambas("hospitalizacion", {"fecha_y_hora_de_alta": "alta"}))
        alta = de_la_bodega(alta, atenciones(staging_dirs))["alta"].dropna()
        esperado = alta.dt.hour.map(lambda h: f"{h:02d}:00 - {(h + 1) % 24:02d}:00").value_counts()

        # Act
        obtenido = consulta(conexion, f"""
            SELECT h.intervalo, count(*) AS n FROM {ESQUEMA}.fact_trauma f
            JOIN {ESQUEMA}.dim_horario h ON h.horario_id = f.hora_alta_id GROUP BY 1""").set_index("intervalo")["n"]

        # Assert
        iguales(esperado, obtenido)
        assert obtenido["23:00 - 00:00"] >= 2, "el alta a las 23:59:45 de cada fuente cae en la última franja"
