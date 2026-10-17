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
__all__ += ["create_cases_router"]


def __getattr__(name: str):
    # Perezoso: quien solo usa la fachada no necesita cargar FastAPI.
    if name == "create_cases_router":
        from modules.cases.api.router import create_cases_router

        return create_cases_router
    raise AttributeError(name)
