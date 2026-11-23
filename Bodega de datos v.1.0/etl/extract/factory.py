# Extractor factory module
from etl.extract.base import BaseExtractor
from etl.extract.excel_extractor import ExcelExtractor
from etl.extract.redcap_extractor import REDCapExtractor

class ExtractorFactory:
    """
    Fábrica encargada de instanciar el extractor correcto según la configuración.
    Usa un registro (Registry Pattern) en vez de condicionales if/elif,
    para que agregar/modificar extractores no requiera tocar esta clase (OCP).
    """

    _registry: dict[str,type[BaseExtractor]] = {
        'excel' : ExcelExtractor,
        'redcap' : REDCapExtractor,
    }
    
    @classmethod
    def register(cls, source_type:str, extractor_cls: type[BaseExtractor]) -> None:
        "Permite registrar nuevos extractores (ej. SQLExtractor) sin modificar la clase"
        cls._registry[source_type.lower()] = extractor_cls


    @classmethod
    def get_extractor(cls, source_type: str, config: dict) -> BaseExtractor:
        """
        Retorna una instancia concreta de BaseExtractor basada en el tipo de origen.
        
        Args:
            source_type (str): Tipo de origen ('excel' o 'redcap').
            config (dict): Parámetros requeridos para inicializar el extractor.
            
        Returns:
            BaseExtractor: Instancia configurada del extractor.
        """

        extractor_cls = cls._registry.get(source_type.lower())
        if extractor_cls is None:
            raise ValueError(
                f"Tipo de origen no soportado: '{source_type}'."
                f"Disponibles: {list(cls._registry.keys())}"
            )

        try:
            return extractor_cls(**config)
        except TypeError as e:
            raise TypeError(
                f"Configuración inválida para '{source_type}': {e}"
            ) from e