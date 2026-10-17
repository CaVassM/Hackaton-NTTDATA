"""ClaimBuilder DETERMINISTA: solo admite citas a version_id recuperados en este
flujo. Un claim con un id no recuperado se rechaza (y queda registrado)."""
import re

from modules.cases.domain import CaseClaim

_WS = re.compile(r"\s+")


def norm_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


class ClaimBuilder:
    def __init__(self, recuperados: set[int]):
        self.recuperados = set(recuperados)
        self.claims: list[CaseClaim] = []
        self.rechazados: list[dict] = []

    def _id(self, prefijo: str) -> str:
        return f"{prefijo}_{len(self.claims) + 1}"

    def add(self, claim: CaseClaim) -> bool:
        ids = set(claim.evidence_ids) | ({claim.version_ref} if claim.version_ref is not None else set())
        ajenos = sorted(ids - self.recuperados)
        if ajenos:
            self.rechazados.append({"claim": claim.model_dump(), "motivo": f"version_id no recuperado: {ajenos}"})
            return False
        if claim.type == "normativa" and not claim.evidence_ids:
            self.rechazados.append({"claim": claim.model_dump(), "motivo": "afirmacion normativa sin evidencia"})
            return False
        self.claims.append(claim)
        return True

    def normativa(self, texto: str, version_id: int, origen: str) -> bool:
        return self.add(CaseClaim(claim_id=self._id("n"), text=norm_ws(texto)[:4000], type="normativa",
                                  evidence_ids=[version_id], version_ref=version_id, origen=origen))

    def dato(self, texto: str, origen: str, version_ref: int | None = None) -> bool:
        return self.add(CaseClaim(claim_id=self._id("d"), text=texto, type="dato_caso",
                                  version_ref=version_ref, origen=origen))

    def inferencia(self, texto: str, origen: str, version_ref: int | None = None) -> bool:
        return self.add(CaseClaim(claim_id=self._id("i"), text=texto, type="inferencia",
                                  version_ref=version_ref, origen=origen))
