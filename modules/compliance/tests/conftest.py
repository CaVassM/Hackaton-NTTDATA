"""Fixtures de compliance: rag (API publica) sobre el corpus SBS limpio + el
anexo SINTETICO, con embeddings y LLM falsos (sin Ollama)."""
import hashlib
import math
import re
from collections.abc import Callable
from datetime import date

import pytest
from pydantic import BaseModel

from modules.compliance import ComplianceFacade, ComplianceSettings, CsvEvidenceSource
from modules.rag import RagFacade, RagSettings
from shared.config import PROJECT_ROOT
from shared.llm import EmbeddingClient, LLMClient

HOY = date(2026, 10, 17)
SBS_TXT = PROJECT_ROOT / "data" / "raw" / "sbs_txt"
ANEXO_SINTETICO = PROJECT_ROOT / "data" / "raw" / "sinteticos" / "04_anexo_infracciones_laft_SINTETICO.txt"
NORMA_2660 = "Resolución SBS N° 2660-2015"
NORMA_SINT = "SINTETICO-ANEXO-INFRACCIONES-LAFT"
EVIDENCIA = PROJECT_ROOT / "data" / "raw" / "compliance" / "evidencia_sintetica.csv"


class HashEmbedder(EmbeddingClient):
    model_name = "fake-hash-compliance"

    def _v(self, text: str) -> list[float]:
        v = [0.0] * 256
        for tok in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 256] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts):
        return [self._v(t) for t in texts]

    def embed_query(self, text):
        return self._v(text)


class FakeLLMClient(LLMClient):
    """chat_json delega en `responder(user_prompt, schema) -> dict`; cuenta llamadas."""

    model_name = "fake-llm"

    def __init__(self, responder: Callable[[str, type[BaseModel]], dict]):
        self.responder = responder
        self.calls = 0

    def generate(self, prompt, **kw):
        raise NotImplementedError

    def chat(self, messages, **kw):
        raise NotImplementedError

    def chat_json(self, messages, schema, *, think=None, options=None):
        self.calls += 1
        out = self.responder(messages[-1]["content"], schema)
        return schema.model_validate(out)


def articulo_del_prompt(prompt: str) -> str:
    return prompt.split("<<<", 1)[1].rsplit(">>>", 1)[0]


def oracion_con(prompt: str, patron: str) -> str | None:
    """Oracion literal del articulo del prompt que contiene `patron`."""
    texto = re.sub(r"\s+", " ", articulo_del_prompt(prompt))
    for o in re.split(r"(?<=\.)\s+", texto):
        if re.search(patron, o):
            return o
    return None


@pytest.fixture(scope="session")
def rag(tmp_path_factory) -> RagFacade:
    d = tmp_path_factory.mktemp("rag")
    facade = RagFacade.from_settings(RagSettings(rag_dir=d / "rag", log_dir=d / "logs"),
                                     embedder=HashEmbedder(), today=lambda: HOY)
    facade.ingest(SBS_TXT)
    facade.ingest(ANEXO_SINTETICO)
    return facade


def make_facade(rag, tmp_path, responder, *, uit=None, norma_inf=NORMA_SINT, evidence=None, auditor=None):
    llm = FakeLLMClient(responder)
    s = ComplianceSettings(compliance_dir=tmp_path / "c", log_dir=tmp_path / "logs", uit_valor=uit,
                           norma_infracciones=norma_inf)
    f = ComplianceFacade.from_settings(s, rag=rag, llm=llm, embedder=HashEmbedder(),
                                       evidence=evidence or CsvEvidenceSource(EVIDENCIA),
                                       today=lambda: HOY, auditor=auditor)
    return f, llm


# ------------------------------------------------------------------ respuestas
def responder_correcto(prompt: str, schema) -> dict:
    """Simula un LLM que cita bien: usa oraciones reales del articulo."""
    if schema.__name__ == "ExtraccionObligaciones":
        obls = []
        if (c := oracion_con(prompt, r"veinticuatro horas \(24\)")):
            obls.append(dict(sujeto="la empresa", accion_requerida="comunicar el ROS a la UIF-Perú",
                             evento_disparador="calificación de la operación como sospechosa",
                             plazo_texto="no más de 24 horas", plazo_valor=24, plazo_unidad="horas",
                             tipo_plazo="calendario", evidencia_requerida="constancia de envío ROSEL", cita_textual=c))
        if (c := oracion_con(prompt, r"dos \(2\) capacitaciones")):
            obls.append(dict(sujeto="el oficial de cumplimiento", accion_requerida="recibir 2 capacitaciones especializadas",
                             plazo_texto="al año", plazo_valor=None, plazo_unidad="anios", tipo_plazo="periodico",
                             cita_textual=c))
        if (c := oracion_con(prompt, r"deben crear un registro")):
            obls.append(dict(sujeto="las empresas", accion_requerida="crear el registro de operaciones", cita_textual=c))
        return {"impone_obligacion": bool(obls), "obligaciones": obls}
    # ExtraccionInfracciones
    infs = []
    if (c := oracion_con(prompt, r"Sanción sintética")) and (num := re.search(r"NUMERAL (\S+)", prompt)):
        numeral_txt = re.sub(r"\s+", " ", articulo_del_prompt(prompt))
        nums = [float(x) for x in re.findall(r"(\d+) UIT|de (\d+) hasta", c) for x in x if x]
        hasta = re.search(r"hasta (\d+) UIT", c)
        desde = re.search(r"de (\d+) hasta", c)
        gravedad = "muy_grave" if "muy graves" in prompt else ("grave" if "graves" in prompt else "leve")
        infs.append(dict(codigo_numeral=num.group(1), descripcion=numeral_txt[:120], gravedad=gravedad,
                         sancion_texto=c, multa_min_uit=float(desde.group(1)) if desde else None,
                         multa_max_uit=float(hasta.group(1)) if hasta else None, cita_textual=numeral_txt,
                         relacionada_con_categoria=True, motivo_relacion="sanciona el incumplimiento"))
    return {"contiene_infracciones": bool(infs), "infracciones": infs}
