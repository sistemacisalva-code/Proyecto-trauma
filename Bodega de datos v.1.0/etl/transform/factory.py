# Transform factory module
from etl.transform.base import BaseTransformer
from etl.transform.excel_transformer import ExcelTransformer
from etl.transform.redcap_transformer import REDCapTransformer


class TransformerFactory:
    """
    Fábrica encargada de instanciar el transformador correcto según la configuración.
    Usa un registro (Registry Pattern) en vez de condicionales if/elif,
    para que agregar/modificar transformers no requiera tocar esta clase (OCP).
    """
    _registry: dict[str, type[BaseTransformer]] = {
        'redcap': REDCapTransformer,
        'excel': ExcelTransformer,
    }

    @classmethod
    def register(cls, source_type: str, transformer_cls: type[BaseTransformer]) -> None:
        "Permite registrar nuevos transformadores (ej. ExcelTransformer) sin modificar la clase"
        cls._registry[source_type.lower()] = transformer_cls

    @classmethod
    def get_transformer(cls, source_type: str, config: dict) -> BaseTransformer:
        """
        Retorna una instancia concreta de BaseTransformer basada en el tipo de origen.

        Args:
            source_type (str): Tipo de origen (por ahora 'redcap').
            config (dict): Parámetros requeridos para inicializar el transformador.

        Returns:
            BaseTransformer: Instancia configurada del transformador.
        """
        transformer_cls = cls._registry.get(source_type.lower())
        if transformer_cls is None:
            raise ValueError(
                f"No hay un transformador disponible para ese origen: '{source_type}'. "
                f"Disponibles: {list(cls._registry.keys())}"
            )
        try:
            return transformer_cls(**config)
        except TypeError as e:
            raise TypeError(
                f"Configuración inválida para '{source_type}': {e}"
            ) from e
