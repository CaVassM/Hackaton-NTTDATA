"""Resumen para el usuario. El LLM (think=false) solo REDACTA a partir de los
claims: si introduce una cifra que no esta en ellos, se usa la plantilla."""
from modules.cases.domain import CaseClaim
from modules.cases.services.numbers import numeros_nuevos
from shared.llm import LLMClient
from shared.logging import get_logger

log = get_logger(__name__)

_SYSTEM = (
    "Eres un asistente de cumplimiento LA/FT. Redacta un resumen breve (3 a 4 oraciones, en espanol) "
    "para un oficial de cumplimiento usando SOLO las afirmaciones dadas. No agregues cifras, fechas, "
    "plazos, montos ni normas que no esten en ellas. No des recomendaciones de reportar ni de bloquear."
)


class Summarizer:
    def __init__(self, llm: LLMClient | None):
        self.llm = llm

    def resumir(self, claims: list[CaseClaim], plantilla: str, contexto: list[str] | None = None) -> tuple[str, str]:
        if self.llm is None or not claims:
            return plantilla, "plantilla"
        lista = "\n".join(f"- ({c.type}) {c.text}" for c in claims)
        try:
            texto = self.llm.chat(
                [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": f"AFIRMACIONES:\n{lista}"}],
                think=False, options={"temperature": 0},
            ).strip()
        except Exception as exc:  # noqa: BLE001 - sin LLM, la plantilla basta
            log.warning("Resumen con LLM fallo (%s); se usa plantilla", exc)
            return plantilla, "plantilla"
        nuevos = numeros_nuevos(texto, [c.text for c in claims] + (contexto or []))
        if not texto or nuevos:
            log.info("Resumen descartado (cifras nuevas %s); se usa plantilla", sorted(nuevos))
            return plantilla, "plantilla"
        return texto, "llm"
