class AuditError(Exception):
    """Base de los errores del modulo audit."""


class PolicyError(AuditError):
    """La politica YAML es invalida o no existe."""


class AuditNotFound(AuditError):
    pass


class PersistenceNotConfigured(AuditError):
    pass
