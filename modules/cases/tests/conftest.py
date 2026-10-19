"""Fixtures de cases: rag/compliance/audit REALES (APIs publicas) sobre el corpus
SBS limpio, con embeddings y LLM falsos. Las obligaciones de prueba se extraen
con un LLM falso que cita bien y se VALIDAN en el test (como haria un humano)."""
import hashlib
import math
import re
from collections.abc import Callable
from datetime import date

import pytest
import yaml
from pydantic import BaseModel

from modules.audit import AuditFacade, AuditSettings
from modules.cases import CasesFacade, CasesSettings
from modules.compliance import ComplianceFacade, ComplianceSettings
from modules.rag import RagFacade, RagSettings
from shared.config import PROJECT_ROOT
from shared.llm import EmbeddingClient, LLMClient

HOY = date(2026, 10, 17)
SBS_TXT = PROJECT_ROOT / "data" / "raw" / "sbs_txt"


class HashEmbedder(EmbeddingClient):
    model_name = "fake-hash-cases"

    def _v(self, text):
        v = [0.0] * 256
        for tok in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 256] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts):
        return [self._v(t) for t in texts]

    def embed_query(self, text):
        return self._v(text)


class FakeLLM(LLMClient):
    """chat -> self.texto; chat_json -> self.json_responder(prompt, schema)."""

    model_name = "fake-llm"

    def __init__(self, texto: str = "", json_responder: Callable[[str, type[BaseModel]], dict] | None = None):
        self.texto = texto
        self.json_responder = json_responder
        self.calls = 0

    def generate(self, prompt, **kw):
        return self.texto

    def chat(self, messages, **kw):
        self.calls += 1
        return self.texto

    def chat_json(self, messages, schema, *, think=None, options=None):
        self.calls += 1
        if self.json_responder is None:
            raise ValueError("sin respuesta configurada")
        return schema.model_validate(self.json_responder(messages[-1]["content"], schema))


def _oracion(prompt: str, patron: str) -> str | None:
    texto = re.sub(r"\s+", " ", prompt.split("<<<", 1)[1].rsplit(">>>", 1)[0])
    return next((o for o in re.split(r"(?<=\.)\s+", texto) if re.search(patron, o)), None)


def _extractor(prompt, schema):
    obls = []
    if (c := _oracion(prompt, r"veinticuatro horas \(24\)")):
        obls.append(dict(sujeto="la empresa", accion_requerida="comunicar el ROS", plazo_valor=24,
                         plazo_unidad="horas", tipo_plazo="calendario", cita_textual=c))
    if (c := _oracion(prompt, r"treinta \(30\) días siguientes a la fecha de ingreso")):
        obls.append(dict(sujeto="la empresa", accion_requerida="capacitar a nuevos ingresos", plazo_valor=30,
                         plazo_unidad="dias", tipo_plazo="calendario", cita_textual=c))
    return {"impone_obligacion": bool(obls), "obligaciones": obls}


@pytest.fixture(scope="session")
def stack(tmp_path_factory):
    d = tmp_path_factory.mktemp("stack")
    rag = RagFacade.from_settings(RagSettings(rag_dir=d / "rag", log_dir=d / "logs"), embedder=HashEmbedder(),
                                  today=lambda: HOY)
    rag.ingest(SBS_TXT)
    audit = AuditFacade.from_settings(AuditSettings(log_dir=d / "alog", audit_dir=d / "audit"), rag=rag, today=lambda: HOY)
    comp = ComplianceFacade.from_settings(
        ComplianceSettings(compliance_dir=d / "c", log_dir=d / "clog", uit_valor=5500.0),
        rag=rag, llm=FakeLLM(json_responder=_extractor), embedder=HashEmbedder(), today=lambda: HOY)
    comp.extract_obligations(["BAN-004", "BAN-007"])
    validadas = {}
    for o in comp.proposals()["obligaciones"]:
        if o.plazo_valor in (24, 30):
            comp.review(o.proposal_id, True, "test")
            validadas[o.categoria] = o
    eventos = d / "eventos.yaml"
    eventos.write_text(yaml.safe_dump({"eventos": {
        "operacion_calificada_sospechosa": {"categoria": "BAN-004", "descripcion": "ROS", "fecha_evento": "calificacion"},
        "ingreso_empleado": {"categoria": "BAN-007", "descripcion": "ingreso", "fecha_evento": "ingreso"},
        "requerimiento_sbs": {"categoria": "BAN-005", "obligaciones": ["BAN-005-03"], "descripcion": "req",
                              "fecha_evento": "recepcion"},
    }}), encoding="utf-8")
    return {"rag": rag, "audit": audit, "compliance": comp, "validadas": validadas, "eventos": eventos, "dir": d}


def make_cases(stack, tmp_path, *, texto="", json_responder=None) -> tuple[CasesFacade, FakeLLM]:
    llm = FakeLLM(texto, json_responder)
    f = CasesFacade.from_settings(
        CasesSettings(cases_dir=tmp_path / "cases", eventos_path=stack["eventos"], log_dir=tmp_path / "logs",
                      cases_audit_mode="direct"),  # aislado del .env local (que puede tener a2a)
        rag=stack["rag"], compliance=stack["compliance"], audit=stack["audit"], llm=llm)
    return f, llm


def caso(**kw) -> dict:
    base = {"case_id": "ROS-2026-0115", "user_id": "u1", "rol": "oficial_cumplimiento",
            "tipo_evento": "operacion_calificada_sospechosa", "fecha_evento": "2026-09-10",
            "fecha_cumplimiento": "2026-09-15", "fecha_referencia": "2026-10-17"}
    return {**base, **kw}
