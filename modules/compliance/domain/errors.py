class ComplianceError(Exception):
    """Base de los errores del modulo compliance."""


class PropuestaNoEncontrada(ComplianceError):
    pass


class EvidenciaInvalida(ComplianceError):
    """El CSV de evidencia no cumple el formato acordado."""
