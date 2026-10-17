class CasesError(Exception):
    """Base de los errores del modulo cases."""


class CaseValidationError(CasesError):
    """Entrada valida en forma pero no en contenido (p. ej. tipo_evento desconocido)."""

    def __init__(self, field: str, message: str, valores_validos: list[str] | None = None):
        super().__init__(message)
        self.field = field
        self.valores_validos = valores_validos or []


class CaseNotFound(CasesError):
    pass
