"""Indice vectorial en Chroma persistente. Un registro por VERSION (id=version_id).

Se indexan todas las versiones, tambien las antiguas: el filtro de vigencia se
decide en SQL, no aqui. Los metadatos son informativos/de depuracion.
"""
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from modules.rag.repositories.interfaces import chunked

# Chroma limita el tamano de cada operacion; troceamos por seguridad.
_BATCH = 1000


def collection_name_for(embed_model: str) -> str:
    """El indice queda ATADO al modelo: vectores de modelos distintos no se
    pueden mezclar, asi que cada modelo tiene su propia coleccion."""
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", embed_model).strip("._-")
    return f"versiones__{slug}"[:63]


def metadata_for(norma_codigo: str, articulo_numero: str, desde: str, hasta: str | None, creada_por: str) -> dict:
    # Chroma no admite None en metadatos: "" significa "sigue vigente".
    return {
        "norma_codigo": norma_codigo,
        "articulo_numero": articulo_numero,
        "vigente_desde": desde,
        "vigente_hasta": hasta or "",
        "creada_por": creada_por,
    }


class ChromaVectorRepository:
    def __init__(self, persist_dir: Path, collection_name: str):
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        # Telemetria apagada: el sistema debe ser 100% local.
        self._client = chromadb.PersistentClient(
            path=str(persist_dir), settings=Settings(anonymized_telemetry=False)
        )
        # embedding_function=None: siempre pasamos los vectores nosotros. Evita
        # que Chroma intente descargar su modelo ONNX por defecto.
        self._col = self._client.get_or_create_collection(
            collection_name,
            configuration={"hnsw": {"space": "cosine"}},
            embedding_function=None,
        )

    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        for idx in chunked(list(range(len(ids))), _BATCH):
            self._col.upsert(
                ids=[str(ids[i]) for i in idx],
                embeddings=[list(embeddings[i]) for i in idx],
                documents=[documents[i] for i in idx],
                metadatas=[metadatas[i] for i in idx],
            )

    def update_metadata(self, ids: Sequence[int], metadatas: Sequence[dict[str, Any]]) -> None:
        for idx in chunked(list(range(len(ids))), _BATCH):
            self._col.update(ids=[str(ids[i]) for i in idx], metadatas=[metadatas[i] for i in idx])

    def existing_ids(self) -> set[int]:
        return {int(i) for i in self._col.get(include=[])["ids"]}

    def query(self, embedding: Sequence[float], k: int) -> list[tuple[int, float]]:
        n = self._col.count()
        if n == 0:
            return []
        res = self._col.query(query_embeddings=[list(embedding)], n_results=min(k, n), include=["distances"])
        # Distancia coseno -> similitud, para que "mas alto = mejor" como en BM25.
        return [(int(i), 1.0 - float(d)) for i, d in zip(res["ids"][0], res["distances"][0])]

    def count(self) -> int:
        return self._col.count()
