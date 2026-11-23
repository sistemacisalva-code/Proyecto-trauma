import pytest

from etl import pipeline


class TestBuildArgParser:
    def test_acepta_el_modo_transform_redcap(self):
        """
        Qué es: prueba unitaria del parser de la línea de comandos.
        Qué hace: interpreta --mode=transform-redcap.
        Esperado: args.mode vale "transform-redcap" y --force queda en False.
        """
        # Arrange + Act: construir el parser e interpretar los argumentos
        args = pipeline.build_arg_parser().parse_args(["--mode=transform-redcap"])

        # Assert: modo reconocido y bandera por defecto apagada
        assert args.mode == "transform-redcap"
        assert args.force is False

    @pytest.mark.parametrize("argv", [[], ["--mode=no-existe"]])
    def test_rechaza_un_modo_ausente_o_desconocido(self, argv):
        """
        Qué es: prueba unitaria de la obligatoriedad de --mode (sin valor por defecto).
        Qué hace: interpreta los argumentos sin --mode y con un modo inexistente.
        Esperado: argparse termina con SystemExit en ambos casos (nadie ejecuta una carga por accidente).
        """
        # Arrange: parser real
        parser = pipeline.build_arg_parser()

        # Act + Assert: ambos casos son rechazados
        with pytest.raises(SystemExit):
            parser.parse_args(argv)


class TestParseArgsCarga:
    def test_acepta_la_carga_con_modelo_y_fuente(self):
        """
        Qué es: prueba unitaria del modo load de la línea de comandos.
        Qué hace: interpreta --mode=load --modelo=completo --fuente=excel --force.
        Esperado: los cuatro argumentos quedan en args tal como se dieron.
        """
        # Arrange + Act: interpretar los argumentos con la validación de combinaciones
        args = pipeline.parse_args(["--mode=load", "--modelo=completo", "--fuente=excel", "--force"])

        # Assert: modo, modelo, fuente y force reconocidos
        assert (args.mode, args.modelo, args.fuente, args.force) == ("load", "completo", "excel", True)

    @pytest.mark.parametrize("argv", [
        ["--mode=load", "--fuente=redcap"],
        ["--mode=load", "--modelo=mini"],
        ["--mode=load", "--modelo=otro", "--fuente=redcap"],
        ["--mode=transform-redcap", "--modelo=completo"],
    ])
    def test_rechaza_combinaciones_invalidas_de_la_carga(self, argv):
        """
        Qué es: prueba unitaria de la validación de combinaciones de parse_args.
        Qué hace: interpreta load sin modelo, load sin fuente, un modelo inexistente y --modelo en otro modo.
        Esperado: SystemExit en los cuatro casos (la carga no tiene modelo ni fuente por defecto).
        """
        # Arrange: argumentos del parámetro

        # Act + Assert: argparse termina el proceso
        with pytest.raises(SystemExit):
            pipeline.parse_args(argv)


class TestParseArgsCorridaCompleta:
    def test_acepta_la_corrida_completa_con_modelo_por_defecto_o_explicito(self):
        """
        Qué es: prueba unitaria del modo all de la línea de comandos.
        Qué hace: interpreta --mode=all solo, y con --modelo=mini --sin-excel --sin-extraccion.
        Esperado: sin modelo queda "completo" y las dos opciones apagadas; con modelo y opciones quedan tal como se
                  dieron.
        """
        # Arrange + Act
        por_defecto = pipeline.parse_args(["--mode=all"])
        explicito = pipeline.parse_args(["--mode=all", "--modelo=mini", "--sin-excel", "--sin-extraccion"])

        # Assert
        assert (por_defecto.mode, por_defecto.modelo, por_defecto.sin_excel, por_defecto.sin_extraccion) == (
            "all", "completo", False, False)
        assert (explicito.modelo, explicito.sin_excel, explicito.sin_extraccion) == ("mini", True, True)

    @pytest.mark.parametrize("argv", [
        ["--mode=all", "--force"],
        ["--mode=all", "--fuente=redcap"],
        ["--mode=all", "--full-refresh"],
        ["--mode=redcap", "--sin-excel"],
        ["--mode=load", "--modelo=completo", "--fuente=redcap", "--sin-extraccion"],
    ])
    def test_rechaza_combinaciones_invalidas_de_la_corrida_completa(self, argv):
        """
        Qué es: prueba unitaria de la validación de combinaciones del modo all.
        Qué hace: interpreta all con --force, con --fuente, con --full-refresh, y --sin-excel o --sin-extraccion en
                  otro modo.
        Esperado: SystemExit en los cinco casos (repetir el Excel a la fuerza es una decisión manual y la fuente la
                  decide la corrida).
        """
        # Arrange: argumentos del parámetro

        # Act + Assert
        with pytest.raises(SystemExit):
            pipeline.parse_args(argv)
