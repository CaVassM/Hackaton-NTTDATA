"""ComplianceFacade: la UNICA puerta del modulo compliance.

    from modules.compliance import ComplianceFacade
    c = ComplianceFacade.from_settings()
    c.extract_obligations(["BAN-004"])          # offline: propuestas
    c.review("obl-5", aprobar=True, revisor="ana")
    report, audit = c.report(date(2026, 10, 17), auditar=True)
"""
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

from modules.compliance.config import ComplianceSettings
from modules.compliance.deadlines import DeadlineEngine
from modules.compliance.domain import Categoria, ComplianceError, EstadoPropuesta, TipoPropuesta
from modules.compliance.evidence import EvidenceSource
from modules.compliance.exposure import ExposureCalculator
from modules.compliance.extraction.categories import seleccionar
from modules.compliance.extraction.infraction_extractor import InfractionExtractor
from modules.compliance.extraction.obligation_extractor import ExtractionSummary, ObligationExtractor
from modules.compliance.reporting import ComplianceReport, ReportBuilder
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
        infractions: InfractionExtractor,
        evidence: EvidenceSource,
        deadlines: DeadlineEngine,
        exposure: ExposureCalculator,
        today: Callable[[], date] = date.today,
        auditor: Any = None,
    ):
        self.settings = settings
        self._rag = rag
        self._repo = repo
        self.categorias = categorias
        self._obligations = obligations
        self._infractions = infractions
        self._today = today
        self._auditor = auditor
        self._reports = ReportBuilder(repo, evidence, deadlines, exposure, uit_configurada=exposure.uit_valor is not None)

    @classmethod
    def from_settings(cls, settings: ComplianceSettings | None = None, **kw: Any) -> "ComplianceFacade":
        from modules.compliance.bootstrap import build_compliance_facade

        return build_compliance_facade(settings, **kw)

    def hoy(self) -> date:
        return self._today()

    # ------------------------------------------------------------ extraccion
    def categorias_validas(self, categorias: list[str] | None) -> list[Categoria]:
        """Valida codigos de categoria (ComplianceError si alguno no existe)."""
        return seleccionar(self.categorias, categorias)

    def extract_obligations(self, categorias: list[str] | None = None, fecha: date | None = None,
                            progress=None) -> ExtractionSummary:
        return self._obligations.run(seleccionar(self.categorias, categorias), fecha or self.hoy(), progress)

    def extract_infractions(self, categorias: list[str] | None = None, fecha: date | None = None,
                            progress=None) -> ExtractionSummary:
        return self._infractions.run(seleccionar(self.categorias, categorias), fecha or self.hoy(), progress)

    # ------------------------------------------------------------ propuestas
    def proposals(self, tipo: TipoPropuesta | None = None,
                  estado: EstadoPropuesta | None = EstadoPropuesta.PROPUESTA) -> dict[str, list]:
        out: dict[str, list] = {}
        if tipo in (None, TipoPropuesta.OBLIGACION):
            out["obligaciones"] = self._repo.list_obligaciones(estado)
        if tipo in (None, TipoPropuesta.INFRACCION):
            out["infracciones"] = self._repo.list_infracciones(estado)
        if tipo in (None, TipoPropuesta.ENLACE):
            out["enlaces"] = self._repo.list_enlaces(estado)
        return out

    def review(self, proposal_id: str, aprobar: bool, revisor: str, comentario: str | None = None) -> None:
        """Validacion humana: quien y cuando quedan en la fila y en revision_log."""
        if not revisor or not revisor.strip():
            raise ComplianceError("La revision humana requiere identificar al revisor")
        tipo, id_ = parse_proposal_id(proposal_id)
        estado = EstadoPropuesta.VALIDADA if aprobar else EstadoPropuesta.RECHAZADA
        self._repo.review(tipo, id_, estado, revisor.strip(), comentario)
        log.info("Revision %s -> %s por %s", proposal_id, estado, revisor)

    # --------------------------------------------------------------- reporte
    def report(self, fecha_corte: date | None = None, categorias: list[str] | None = None, *,
               auditar: bool = False, user_id: str = "compliance", role: str = "oficial_cumplimiento"):
        """(ComplianceReport, AuditResult | None). Solo usa filas VALIDADAS."""
        rep = self._reports.build(fecha_corte or self.hoy(), categorias)
        audit = None
        if auditar:
            if self._auditor is None:
                raise ComplianceError("No hay auditor configurado (inyecta AuditFacade en from_settings)")
            audit = self._auditor.evaluate(rep.to_audit_request(
                interaction_id=f"compliance-{rep.fecha_corte}-{rep.generado_en:%H%M%S}", user_id=user_id, role=role))
        return rep, audit
