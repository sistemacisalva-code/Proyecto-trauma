# Loader del modelo completo
from etl.load.warehouse.por_contrato import CargaPorContrato


class CompletoLoader(CargaPorContrato):
    """
    Carga el staging de una fuente en el modelo completo (esquema trauma_completo). Todo el mapeo está en
    config/contratos/completo.yaml; esta clase solo nombra el modelo y su esquema.
    """
    modelo = "completo"
    esquema = "trauma_completo"
