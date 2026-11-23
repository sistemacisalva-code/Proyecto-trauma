"""Registro de la transformación por instrumento de REDCap.

Cada módulo expone NOMBRE, CATEGORICAS y `transformar(df, reporte, bloques)`, donde `bloques` trae los
instrumentos ya transformados (para las dependencias declaradas en bloques.DEPENDENCIAS).
El único instrumento sin módulo es examen_fisico, que pasa sin cambios. motivo_de_consulta (sustancias), comorbilidades,
complicaciones y cie_10_diagnosticos (etiqueta CIE-10 canónica) tienen módulo desde 2026-10-20.
"""
from etl.transform.redcap.bloques import INSTRUMENTOS_ESPERADOS
from etl.transform.redcap.instrumentos import (
    cie_10_diagnosticos,
    comorbilidades,
    complicaciones,
    hospitalizacion,
    imagenes,
    informacion_demografica,
    laboratorio,
    liquidos,
    mecanismo_de_lesion,
    motivo_de_consulta,
    procedimientos,
    puntuacion_de_severidad,
    signos_vitales,
    uci,
)

_MODULOS = (informacion_demografica, motivo_de_consulta, comorbilidades, mecanismo_de_lesion, signos_vitales, puntuacion_de_severidad,
            imagenes, laboratorio, hospitalizacion, complicaciones, cie_10_diagnosticos, procedimientos, liquidos, uci)

_ATRIBUTOS_REQUERIDOS = ("NOMBRE", "CATEGORICAS", "transformar")


def _validar_contrato(modulos) -> None:
    """Falla al importar, con un mensaje explícito, si un módulo no cumple el contrato de instrumento."""
    for m in modulos:
        faltantes = [a for a in _ATRIBUTOS_REQUERIDOS if not hasattr(m, a)]
        if faltantes:
            raise AttributeError(f"El módulo '{m.__name__}' no cumple el contrato de instrumento: "
                                 f"le falta {faltantes}. Debe definir {list(_ATRIBUTOS_REQUERIDOS)}.")
        if not callable(m.transformar):
            raise TypeError(f"El módulo '{m.__name__}': 'transformar' debe ser una función "
                            "transformar(df, reporte, bloques).")

    nombres = [m.NOMBRE for m in modulos]
    repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
    if repetidos:
        raise ValueError(f"Hay instrumentos registrados más de una vez: {repetidos}")

    # Un NOMBRE mal escrito dejaría al módulo sin ejecutarse y sin ningún error
    desconocidos = sorted(set(nombres) - set(INSTRUMENTOS_ESPERADOS))
    if desconocidos:
        raise ValueError(f"NOMBRE no reconocido como instrumento esperado: {desconocidos}. "
                         f"Esperados: {list(INSTRUMENTOS_ESPERADOS)}")


_validar_contrato(_MODULOS)

TRANSFORMACIONES = {m.NOMBRE: m.transformar for m in _MODULOS}
CATEGORICAS = {m.NOMBRE: m.CATEGORICAS for m in _MODULOS}
