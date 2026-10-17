"""Indice lexico BM25 (rank_bm25) persistido en disco.

Se persiste el corpus TOKENIZADO en JSON (no el objeto con pickle): cargarlo es
seguro y reconstruir BM25Okapi desde tokens es instantaneo a esta escala.
"""
import json
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path

from rank_bm25 import BM25Okapi

_FORMAT_VERSION = 1

# Stopwords minimas del espanol normativo. Sin ellas "de", "la", "el" dominan BM25.
_STOPWORDS = frozenset(
    """a al con de del el en es la las lo los o para por que se su sus un una y
    e u le les ser sera son como cual cuando este esta estos estas dicho dicha""".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    # Sin acentos y en minusculas: "Artículo" y "articulo" deben coincidir.
    norm = unicodedata.normalize("NFKD", text.lower())
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    return [t for t in _TOKEN.findall(norm) if t not in _STOPWORDS]


class Bm25LexicalRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._ids: list[int] = []
        self._bm25: BM25Okapi | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("format") != _FORMAT_VERSION:
            return  # formato viejo: se reconstruye en la proxima ingesta
        self._set(data["ids"], data["tokens"])

    def _set(self, ids: list[int], tokens: list[list[str]]) -> None:
        self._ids = ids
        # BM25Okapi revienta con corpus vacio.
        self._bm25 = BM25Okapi(tokens) if tokens else None

    def rebuild(self, ids: Sequence[int], texts: Sequence[str]) -> None:
        tokens = [tokenize(t) for t in texts]
        self._set(list(ids), tokens)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"format": _FORMAT_VERSION, "ids": list(ids), "tokens": tokens}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.path)  # escritura atomica: nunca queda un indice a medias

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        q = tokenize(query)
        if self._bm25 is None or not q:
            return []
        scores = self._bm25.get_scores(q)
        ranked = sorted(zip(self._ids, scores), key=lambda p: p[1], reverse=True)
        return [(vid, float(s)) for vid, s in ranked[:k] if s > 0]

    def count(self) -> int:
        return len(self._ids)
