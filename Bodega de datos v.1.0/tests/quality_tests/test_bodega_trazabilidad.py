"""
TC-CAL-12, TC-CAL-13, TC-CAL-14 y TC-CAL-33: reglas de trazabilidad (QR-TRZ-01, QR-TRZ-02 y QR-TRZ-03) y verificación del
conjunto con rol lector y carpeta de reportes, sobre la bodega cargada con el staging sintético.

Cada prueba indica: que es, que hace y que se espera como resultado, y su cuerpo
sigue el patron Arrange (preparar), Act (ejecutar), Assert (verificar).
Los reportes de la transformación se simulan con carpetas vacías en un directorio temporal (solo importa que existan);
la cuarentena de QR-TRZ-03, con Parquet sintéticos de una sola columna en otro directorio temporal; los defectos de
QR-TRZ-02 y QR-TRZ-03 se inyectan en la transacción de la prueba, que se revierte al terminar.
"""
import pandas as pd
from sqlalchemy import text

from etl.quality.bodega import (
    verificar_bodega, verificar_cuarentena_en_disco, verificar_reportes_de_transformacion, verificar_tablas_en_detalle,
)
from etl.quality.reporte import estado, leer_bitacora
from tests.quality_tests.ayudas import por_regla


def _crear_reportes(base, cargas, fuentes) -> None:
    """Una carpeta `<fuente>/run_id=<staging>` por carga de las fuentes pedidas, como las deja la transformación."""
    for carga in cargas:
        if carga.fuente in fuentes:
            (base / carga.fuente / f"run_id={carga.run_id_staging}").mkdir(parents=True)


class TestTrazabilidadReportes:
    def test_tc_cal_12_cumple_cuando_existen_los_reportes(self, conexion, contrato, tmp_path):
        """
        Que es: prueba de calidad de la regla QR-TRZ-01 (reporte de la transformación en disco), caso que cumple.
        Que hace: crea la carpeta del reporte de cada carga y verifica la última carga exitosa de cada fuente.
        Esperado: dos verificaciones (Excel y REDCap), ambas sin incumplimientos.
        """
        # Arrange: reportes simulados de las dos cargas
        cargas, _ = leer_bitacora(conexion, "completo")
        _crear_reportes(tmp_path, cargas, {"excel", "redcap"})

        # Act
        resultados = verificar_reportes_de_transformacion(conexion, contrato, str(tmp_path))

        # Assert
        assert len(resultados) == 2 and all(r.evaluadas == 1 and r.cumple for r in resultados)

    def test_tc_cal_12_detecta_un_reporte_ausente(self, conexion, contrato, tmp_path):
        """
        Que es: prueba de calidad de la regla QR-TRZ-01, caso defectuoso.
        Que hace: crea el reporte de la carga del Excel y deja sin reporte la de REDCap.
        Esperado: REDCap reporta 1 incumplimiento y el Excel, 0.
        """
        # Arrange
        cargas, _ = leer_bitacora(conexion, "completo")
        _crear_reportes(tmp_path, cargas, {"excel"})

        # Act
        resultados = verificar_reportes_de_transformacion(conexion, contrato, str(tmp_path))

        # Assert
        (excel,) = por_regla(resultados, "QR-TRZ-01", "excel")
        (redcap,) = por_regla(resultados, "QR-TRZ-01", "redcap")
        assert (excel.incumplen, redcap.incumplen) == (0, 1)


def _con_cuarentena(conexion, ruta, filas: int = 2) -> None:
    """
    Registra una carga exitosa del Excel con `filas` filas en cuarentena en la tabla base y la carpeta `ruta` (la que
    pase la prueba), que pasa a ser la última del Excel. Ya reconcilia: 5 leídas = 5 - filas cargadas + filas apartadas.
    """
    carga = conexion.execute(text(
        "INSERT INTO etl_control.carga (modelo, fuente, run_id_staging, filas_origen, filas_cargadas, filas_no_usadas, "
        "filas_cuarentena, ruta_cuarentena, exitosa) VALUES ('completo', 'excel', 'sintetico', 5, :c, 0, :q, :r, true) "
        "RETURNING id"), {"c": 5 - filas, "q": filas, "r": str(ruta)}).scalar_one()
    conexion.execute(text(
        "INSERT INTO etl_control.carga_detalle (carga_id, destino, tabla_staging, leidas, cargadas, cuarentena) "
        "VALUES (:k, 'fact_trauma', 'informacion_demografica', 5, :c, :q)"), {"k": carga, "c": 5 - filas, "q": filas})


def _parquet(carpeta, tabla: str, filas: int) -> None:
    """Un Parquet sintético de `filas` filas y una columna, como los que deja la cuarentena."""
    carpeta.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"x": range(filas)}).to_parquet(carpeta / f"{tabla}.parquet", index=False)


class TestTrazabilidadCuarentena:
    def test_tc_cal_33_cumple_cuando_la_cuarentena_esta_en_disco(self, conexion, contrato, tmp_path):
        """
        Que es: prueba de calidad de la regla QR-TRZ-03 (la cuarentena de la bitácora está en disco), caso que cumple.
        Que hace: registra una carga del Excel con 2 filas en cuarentena y escribe un Parquet de 2 filas en su carpeta.
        Esperado: el Excel evalúa 1 tabla sin incumplimientos y REDCap (la carga del fixture) tampoco incumple.
        """
        # Arrange
        _parquet(tmp_path / "run", "informacion_demografica", 2)
        _con_cuarentena(conexion, tmp_path / "run")

        # Act
        resultados = verificar_cuarentena_en_disco(conexion, contrato)

        # Assert
        (excel,) = por_regla(resultados, "QR-TRZ-03", "excel")
        (redcap,) = por_regla(resultados, "QR-TRZ-03", "redcap")
        assert (excel.evaluadas, excel.incumplen) == (1, 0) and redcap.cumple

    def test_tc_cal_33_cumple_sin_filas_en_cuarentena(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-TRZ-03, caso sin cuarentena.
        Que hace: verifica la bodega cargada por el fixture, cuyas cargas no tienen cuarentena o la tienen en su carpeta.
        Esperado: una verificación por fuente y ninguna incumple.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_cuarentena_en_disco(conexion, contrato)

        # Assert
        assert sorted(r.detalle.split(" ")[0] for r in resultados) == ["excel", "redcap"]
        assert all(r.cumple for r in resultados)

    def test_tc_cal_33_detecta_un_parquet_con_otro_numero_de_filas(self, conexion, contrato, tmp_path):
        """
        Que es: prueba de calidad de la regla QR-TRZ-03, caso defectuoso (filas perdidas en disco).
        Que hace: registra 2 filas en cuarentena y deja un Parquet con 1.
        Esperado: el Excel reporta 1 incumplimiento.
        """
        # Arrange
        _parquet(tmp_path / "run", "informacion_demografica", 1)
        _con_cuarentena(conexion, tmp_path / "run")

        # Act
        resultados = verificar_cuarentena_en_disco(conexion, contrato)

        # Assert
        (excel,) = por_regla(resultados, "QR-TRZ-03", "excel")
        assert excel.incumplen == 1

    def test_tc_cal_33_detecta_una_carpeta_inexistente_y_un_parquet_de_mas(self, conexion, contrato, tmp_path):
        """
        Que es: prueba de calidad de la regla QR-TRZ-03, casos defectuosos (carpeta borrada y archivo no registrado).
        Que hace: registra una cuarentena cuya carpeta no existe; luego la crea con el Parquet correcto y otro de una
                  tabla que la bitácora no cuenta.
        Esperado: sin la carpeta, el Excel reporta 1 incumplimiento (la tabla esperada); con el Parquet de más, también 1
                  (el archivo no registrado).
        """
        # Arrange: carga con 2 filas en cuarentena y carpeta ausente
        _con_cuarentena(conexion, tmp_path / "run")

        # Act + Assert: carpeta inexistente
        (sin_carpeta,) = por_regla(verificar_cuarentena_en_disco(conexion, contrato), "QR-TRZ-03", "excel")
        assert sin_carpeta.incumplen == 1

        # Arrange: la carpeta con el Parquet correcto y uno que la bitácora no cuenta
        _parquet(tmp_path / "run", "informacion_demografica", 2)
        _parquet(tmp_path / "run", "signos_vitales", 1)

        # Act + Assert: archivo no registrado
        (de_mas,) = por_regla(verificar_cuarentena_en_disco(conexion, contrato), "QR-TRZ-03", "excel")
        assert de_mas.incumplen == 1


class TestTrazabilidadTablasEnDetalle:
    def test_tc_cal_13_cumple_en_la_bodega_cargada(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-TRZ-02 (toda tabla de staging con un uso), caso que cumple.
        Que hace: compara las tablas de staging que usa el contrato en cada fuente con las del detalle de su última carga.
        Esperado: una verificación por fuente, con tablas evaluadas y ninguna sin uso.
        """
        # Arrange: bodega cargada por el fixture del módulo

        # Act
        resultados = verificar_tablas_en_detalle(conexion, contrato)

        # Assert
        assert sorted(r.detalle.split(" ")[0] for r in resultados) == ["excel", "redcap"]
        assert all(r.evaluadas > 0 and r.cumple for r in resultados)

    def test_tc_cal_13_detecta_una_tabla_sin_uso(self, conexion, contrato):
        """
        Que es: prueba de calidad de la regla QR-TRZ-02, caso defectuoso.
        Que hace: borra del detalle de la carga de REDCap todos los usos de la tabla de signos vitales.
        Esperado: REDCap reporta 1 tabla sin uso y el Excel, 0.
        """
        # Arrange
        conexion.execute(text(
            "DELETE FROM etl_control.carga_detalle WHERE tabla_staging = 'signos_vitales' "
            "AND carga_id = (SELECT max(id) FROM etl_control.carga)"))

        # Act
        resultados = verificar_tablas_en_detalle(conexion, contrato)

        # Assert
        (redcap,) = por_regla(resultados, "QR-TRZ-02", "redcap")
        (excel,) = por_regla(resultados, "QR-TRZ-02", "excel")
        assert (redcap.incumplen, excel.incumplen) == (1, 0)


class TestVerificacionConParametros:
    def test_tc_cal_14_la_bodega_cumple_con_lector_y_reportes(self, conexion, contrato, bd_prueba, tmp_path):
        """
        Que es: prueba de calidad del conjunto completo de verificaciones, con rol lector y carpeta de reportes.
        Que hace: ejecuta verificar_bodega dando el rol lector de la base de pruebas y los reportes simulados.
        Esperado: aparecen QR-SEG-01 y QR-TRZ-01 además de las otras reglas, y ninguna falla.
        """
        # Arrange
        cargas, _ = leer_bitacora(conexion, "completo")
        _crear_reportes(tmp_path, cargas, {"excel", "redcap"})

        # Act
        resultados = verificar_bodega(conexion, contrato, lector=bd_prueba["reader"], reportes_dir=str(tmp_path))

        # Assert
        assert {r.regla for r in resultados} >= {"QR-SEG-01", "QR-SEG-02", "QR-TRZ-01", "QR-TRZ-02", "QR-TRZ-03"}
        assert [r for r in resultados if estado(r) == "Falla"] == []
