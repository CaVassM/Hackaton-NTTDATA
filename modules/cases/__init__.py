"""Modulo cases: evalua casos de cumplimiento y preguntas normativas, auditados.

INTERFAZ PUBLICA:

    from modules.cases import CasesFacade, CaseInput, CaseResult, QuestionInput, ...
"""
from modules.cases.config import CasesSettings
from modules.cases.domain import (
    BatchItem,
    CaseClaim,
    CaseInput,
    CaseNotFound,
    CaseResult,
    CasesError,
    CaseValidationError,
    QuestionInput,
    QuestionResult,
)
from modules.cases.facade import CasesFacade

__all__ = [
    "BatchItem",
    "CaseClaim",
    "CaseInput",
    "CaseNotFound",
    "CaseResult",
    "CaseValidationError",
    "CasesError",
    "CasesFacade",
    "CasesSettings",
    "QuestionInput",
    "QuestionResult",
]
