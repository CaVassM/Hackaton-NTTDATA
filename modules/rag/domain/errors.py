class RagError(Exception):
    """Base de los errores del modulo rag."""


class NormaNoEncontrada(RagError):
    pass


class ArticuloNoEncontrado(RagError):
    pass


class VersionNoEncontrada(RagError):
    pass


class IngestaError(RagError):
    pass
