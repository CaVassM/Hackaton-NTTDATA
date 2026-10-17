"""ComplianceReport: estado por obligacion VALIDADA, atrasos, infracciones
VALIDADAS enlazadas (enlace validado) y exposicion potencial, con citas.

Las propuestas no validadas NUNCA entran en estados ni montos: se listan
aparte, rotuladas como propuestas.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from modules.audit import CandidateResponse, Claim, ClaimType
from modules.compliance.domain import (
    GRAVEDAD_ESTADO,
    ROTULO_EXPOSICION,
    EstadoPlazo,
    EstadoPropuesta,
    Exposicion,
    Infraccion,
    Obligacion,
    ResultadoPlazo,
)
from modules.compliance.deadlines import DeadlineEngine
from modules.compliance.evidence import EvidenceSource
from modules.compliance.exposure import ExposureCalculator
from modules.compliance.repositories import SqliteComplianceRepository

AVISO_CORPUS = ("El corpus normativo no garantiza estar completo ni ser la version consolidada oficial vigente: "
                "validar contra el portal de la SBS.")


@dataclass(frozen=True)
class CitaReporte:
    tipo: str  # obligacion | infraccion
    version_id: int
    norma: str
    articulo: str
    cita_textual: str


@dataclass(frozen=True)
class InfraccionReporte:
    infraccion: Infraccion
    exposicion: Exposicion
    sintetica: bool


@dataclass(frozen=True)
class ItemReporte:
    obligacion: Obligacion
    estado: EstadoPlazo
    dias_atraso: int
    casos: list[ResultadoPlazo]
    infracciones: list[InfraccionReporte]
    rango_uit: tuple[float | None, float | None]
    rango_soles: tuple[float | None, float | None]
    citas: list[CitaReporte]


@dataclass(frozen=True)
class ComplianceReport:
    fecha_corte: date
    generado_en: datetime
    items: list[ItemReporte]
    propuestas_pendientes: dict[str, int]
    advertencias: list[str]
    rotulo: str = ROTULO_EXPOSICION

    def to_candidate_response(self) -> CandidateResponse:
        """Contrato de modules/audit: una afirmacion normativa por cita (evidence
        = version_id) y los datos del caso / exposicion como afirmaciones no
        normativas (audit las deja pendientes => el reporte sale WARN, a proposito)."""
        claims: list[Claim] = []
        partes: list[str] = []
        for it in self.items:
            o = it.obligacion
            pre = o.codigo.replace("-", "_")
            claims.append(Claim(claim_id=f"{pre}_norma", text=o.cita_textual[:4000], type=ClaimType.NORMATIVA,
                                evidence_ids=[o.version_id]))
            for k, ir in enumerate(it.infracciones, 1):
                claims.append(Claim(claim_id=f"{pre}_inf{k}", text=ir.infraccion.cita_textual[:4000],
                                    type=ClaimType.NORMATIVA, evidence_ids=[ir.infraccion.version_id]))
            # Un dato del caso por fila de evidencia: cada uno es una afirmacion distinta.
            for k, c in enumerate(it.casos, 1):
                claims.append(Claim(claim_id=f"{pre}_caso{k}", type=ClaimType.DATO_CASO,
                                    text=f"Caso {c.sujeto_id or '-'} de {o.codigo}: {c.estado}, "
                                         f"atraso {c.dias_atraso} dias."))
            # La exposicion siempre se declara (aunque sea "monto no determinado").
            rango = _rango_txt(it) if it.infracciones else "monto no determinado (sin infraccion validada enlazada)"
            claims.append(Claim(claim_id=f"{pre}_exp", type=ClaimType.INFERENCIA,
                                text=f"Obligacion {o.codigo}: {ROTULO_EXPOSICION}, {rango}."))
            estado = f"Obligacion {o.codigo}: estado {it.estado}, atraso maximo {it.dias_atraso} dias."
            partes.append(f"{estado} {rango}.")
        texto = " ".join(partes) or "Sin obligaciones validadas para reportar."
        if not claims:
            claims.append(Claim(claim_id="vacio", text=texto, type=ClaimType.DATO_CASO))
        return CandidateResponse(text=f"[{ROTULO_EXPOSICION}] {texto}"[:20000], claims=claims[:50])

    def to_audit_request(self, *, interaction_id: str, user_id: str, role: str = "oficial_cumplimiento") -> dict[str, Any]:
        return {
            "interaction_id": interaction_id,
            "user_id": user_id,
            "role": role,
            "query": f"Reporte de cumplimiento LA/FT al {self.fecha_corte}",
            "effective_date": self.fecha_corte.isoformat(),
            "use_case": "reporte_cumplimiento",
            "candidate": self.to_candidate_response().model_dump(mode="json"),
        }


@dataclass(frozen=True)
class EvaluacionCaso:
    """Resultado de ComplianceFacade.evaluar_caso (lo consume modules/cases)."""

    categoria: str
    fecha_corte: date
    items: list[ItemReporte]  # obligaciones VALIDADAS con plazos, infracciones y exposicion
    sin_validar: list[Obligacion]  # aplicarian, pero aun son propuestas: no se calcula nada
    no_encontradas: list[str]  # codigos pedidos que no existen
    pendientes_categoria: int = 0
    rotulo: str = ROTULO_EXPOSICION


def _rango_txt(it: ItemReporte) -> str:
    mn, mx = it.rango_uit
    if mn is None and mx is None:
        return "monto no determinado"
    uit = f"{mn if mn is not None else '?'}-{mx if mx is not None else '?'} UIT"
    smn, smx = it.rango_soles
    soles = f" (S/ {smn if smn is not None else '?'} - S/ {smx if smx is not None else '?'})" if smx is not None else ""
    return uit + soles


class ReportBuilder:
    def __init__(self, repo: SqliteComplianceRepository, evidence: EvidenceSource, deadlines: DeadlineEngine,
                 exposure: ExposureCalculator, *, uit_configurada: bool):
        self.repo, self.evidence, self.deadlines, self.exposure = repo, evidence, deadlines, exposure
        self.uit_configurada = uit_configurada

    def build(self, fecha_corte: date, categorias: list[str] | None = None) -> ComplianceReport:
        cats = {c.upper() for c in categorias} if categorias else None
        obligaciones = [o for o in self.repo.list_obligaciones(EstadoPropuesta.VALIDADA)
                        if cats is None or o.categoria in cats]
        enlaces = [e for e in self.repo.list_enlaces(EstadoPropuesta.VALIDADA) if e.relacionada]
        items = [self._item(o, enlaces, fecha_corte) for o in obligaciones]

        advertencias = [AVISO_CORPUS]
        if any(ir.sintetica for it in items for ir in it.infracciones):
            advertencias.append("Hay infracciones tomadas de un anexo SINTETICO (no normativa real): "
                                "sus montos son solo de demostracion.")
        if not self.uit_configurada:
            advertencias.append("UIT_VALOR no configurado: los rangos se muestran solo en UIT.")
        pendientes = {
            "obligaciones": len(self.repo.list_obligaciones(EstadoPropuesta.PROPUESTA)),
            "infracciones": len(self.repo.list_infracciones(EstadoPropuesta.PROPUESTA)),
            "enlaces": len(self.repo.list_enlaces(EstadoPropuesta.PROPUESTA)),
        }
        return ComplianceReport(fecha_corte, datetime.now(timezone.utc), items, pendientes, advertencias)

    def evaluar_caso(self, categoria: str, evidencias: list, fecha_corte: date,
                     codigos: list[str] | None = None) -> "EvaluacionCaso":
        """Un caso puntual (evidencia en memoria, no el CSV) contra las obligaciones
        de la categoria. Solo las VALIDADAS se calculan; el resto se informa aparte."""
        categoria = categoria.upper()
        todas = self.repo.list_obligaciones(categoria=categoria)
        if codigos:
            pedidos = [c.upper() for c in codigos]
            por_codigo = {o.codigo: o for o in todas}
            candidatas = [por_codigo[c] for c in pedidos if c in por_codigo]
            no_encontradas = [c for c in pedidos if c not in por_codigo]
        else:
            candidatas, no_encontradas = todas, []
        validadas = [o for o in candidatas if o.revision.estado == EstadoPropuesta.VALIDADA]
        sin_validar = [o for o in candidatas if o.revision.estado == EstadoPropuesta.PROPUESTA]
        enlaces = [e for e in self.repo.list_enlaces(EstadoPropuesta.VALIDADA, categoria) if e.relacionada]
        items = [self._item(o, enlaces, fecha_corte, evidencias) for o in validadas]
        return EvaluacionCaso(categoria, fecha_corte, items, sin_validar, no_encontradas,
                              pendientes_categoria=sum(o.revision.estado == EstadoPropuesta.PROPUESTA for o in todas))

    def _item(self, o: Obligacion, enlaces, fecha_corte: date, evidencias: list | None = None) -> ItemReporte:
        filas = self.evidence.para(o) if evidencias is None else evidencias
        casos = self.deadlines.evaluar(o, filas, fecha_corte)
        estado = max((c.estado for c in casos), key=GRAVEDAD_ESTADO.get)
        infr = []
        for e in enlaces:
            if e.categoria != o.categoria:
                continue
            inf = self.repo.get_infraccion(e.infraccion_id)
            if inf.revision.estado != EstadoPropuesta.VALIDADA:  # enlace validado pero infraccion no: fuera
                continue
            infr.append(InfraccionReporte(inf, self.exposure.calcular(inf), inf.norma_codigo.upper().startswith("SINTETICO")))
        mins = [ir.exposicion.multa_min_uit for ir in infr if ir.exposicion.multa_min_uit is not None]
        maxs = [ir.exposicion.multa_max_uit for ir in infr if ir.exposicion.multa_max_uit is not None]
        smins = [ir.exposicion.min_soles for ir in infr if ir.exposicion.min_soles is not None]
        smaxs = [ir.exposicion.max_soles for ir in infr if ir.exposicion.max_soles is not None]
        citas = [CitaReporte("obligacion", o.version_id, o.norma_codigo, o.articulo_numero, o.cita_textual)] + [
            CitaReporte("infraccion", ir.infraccion.version_id, ir.infraccion.norma_codigo,
                        ir.infraccion.articulo_numero, ir.infraccion.cita_textual) for ir in infr]
        return ItemReporte(
            obligacion=o, estado=estado, dias_atraso=max((c.dias_atraso for c in casos), default=0), casos=casos,
            infracciones=infr,
            rango_uit=(min(mins) if mins else None, max(maxs) if maxs else None),
            rango_soles=(min(smins) if smins else None, max(smaxs) if smaxs else None),
            citas=citas,
        )
