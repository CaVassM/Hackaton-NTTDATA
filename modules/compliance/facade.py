"""ComplianceFacade: la UNICA puerta del modulo compliance."""
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

from modules.compliance.config import ComplianceSettings
from modules.compliance.domain import Categoria, ComplianceError, EstadoPropuesta, TipoPropuesta
from modules.compliance.extraction.categories import seleccionar
from modules.compliance.extraction.obligation_extractor import ExtractionSummary, ObligationExtractor
from modules.compliance.repositories import SqliteComplianceRepository
from shared.logging import get_logger

if TYPE_CHECKING:
    from modules.rag import RagFacade

log = get_logger(__name__)


def parse_proposal_id(pid: str) -> tuple[TipoPropuesta, int]:
    """'obl-12' -> (OBLIGACION, 12)."""
    try:
        tipo, num = pid.strip().lower().split("-", 1)
        return TipoPropuesta(tipo), int(num)
    except ValueError as exc:
        raise ComplianceError(f"id de propuesta invalido: {pid!r} (formato obl-N | inf-N | enl-N)") from exc


class ComplianceFacade:
    def __init__(
        self,
        *,
        settings: ComplianceSettings,
        rag: "RagFacade",
        repo: SqliteComplianceRepository,
        categorias: list[Categoria],
        obligations: ObligationExtractor,
        today: Callable[[], date] = date.today,
        **extra: Any,
    ):
        self.settings = settings
        self._rag = rag
        self._repo = repo
        self.categorias = categorias
        self._obligations = obligations
        self._today = today
        self._extra = extra  # extractores/motores que se agregan en pasos siguientes

    @classmethod
    def from_settings(cls, settings: ComplianceSettings | None = None, **kw: Any) -> "ComplianceFacade":
        from modules.compliance.bootstrap import build_compliance_facade

        return build_compliance_facade(settings, **kw)

    def hoy(self) -> date:
        return self._today()

    # ------------------------------------------------------------ extraccion
    def extract_obligations(
        self, categorias: list[str] | None = None, fecha: date | None = None, progress=None
    ) -> ExtractionSummary:
        return self._obligations.run(seleccionar(self.categorias, categorias), fecha or self.hoy(), progress)

    # ------------------------------------------------------------ propuestas
    def proposals(self, tipo: TipoPropuesta | None = None, estado: EstadoPropuesta | None = EstadoPropuesta.PROPUESTA):
        out: dict[str, list] = {}
        if tipo in (None, TipoPropuesta.OBLIGACION):
            out["obligaciones"] = self._repo.list_obligaciones(estado)
        if tipo in (None, TipoPropuesta.INFRACCION):
            out["infracciones"] = self._repo.list_infracciones(estado)
        if tipo in (None, TipoPropuesta.ENLACE):
            out["enlaces"] = self._repo.list_enlaces(estado)
        return out

    def review(self, proposal_id: str, aprobar: bool, revisor: str, comentario: str | None = None) -> None:
        if not revisor or not revisor.strip():
            raise ComplianceError("La revision humana requiere identificar al revisor")
        tipo, id_ = parse_proposal_id(proposal_id)
        estado = EstadoPropuesta.VALIDADA if aprobar else EstadoPropuesta.RECHAZADA
        self._repo.review(tipo, id_, estado, revisor.strip(), comentario)
        log.info("Revision %s -> %s por %s", proposal_id, estado, revisor)
