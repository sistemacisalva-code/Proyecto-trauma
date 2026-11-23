# Loader factory module
from etl.load.warehouse.base import BaseLoader
from etl.load.warehouse.completo_loader import CompletoLoader

MODELOS = ("completo", "mini")


class LoaderFactory:
    """
    Fábrica encargada de instanciar el Loader del modelo destino.
    Usa un registro (Registry Pattern) en vez de condicionales if/elif, igual que ExtractorFactory y
    TransformerFactory: agregar un modelo es registrar su clase, sin tocar esta.

    Hoy solo está registrado CompletoLoader; MiniLoader se agregará cuando se cargue el modelo mini.
    """
    _registry: dict[str, type[BaseLoader]] = {
        "completo": CompletoLoader,
    }

    @classmethod
    def register(cls, modelo: str, loader_cls: type[BaseLoader]) -> None:
        "Permite registrar el Loader de un modelo sin modificar la clase"
        cls._registry[modelo.lower()] = loader_cls

    @classmethod
    def get_loader(cls, modelo: str, config: dict) -> BaseLoader:
        """
        Retorna una instancia concreta de BaseLoader para el modelo destino.

        Args:
            modelo (str): modelo de la bodega ('completo' o 'mini').
            config (dict): parámetros del Loader (fuente, engine, staging_dir, ruta_contrato, quarantine_dir, force).

        Returns:
            BaseLoader: Instancia configurada del Loader.
        """
        loader_cls = cls._registry.get(modelo.lower())
        if loader_cls is None:
            raise ValueError(
                f"No hay un Loader disponible para el modelo: '{modelo}'. "
                f"Disponibles: {list(cls._registry.keys())}"
            )
        try:
            return loader_cls(**config)
        except TypeError as e:
            raise TypeError(
                f"Configuración inválida para '{modelo}': {e}"
            ) from e
