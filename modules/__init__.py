"""Modulos del sistema. Cada uno expone su interfaz publica en su `__init__`.

Regla: un modulo solo importa de otro lo que este exporta en su paquete raiz
(p. ej. `from modules.rag import RagFacade`), nunca sus internals.
"""
