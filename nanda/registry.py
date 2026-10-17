"""AgentRegistry local en YAML: register / resolve / list_capabilities.

Sustituto local de un indice NANDA: mapea agent_id -> URL base + capacidades.
La verdad sobre COMO hablarle a un agente sigue estando en su Agent Card; el
registro solo dice DONDE esta y QUE ofrece.
"""
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_FORMAT_VERSION = 1


class RegistryError(Exception):
    pass


class AgentNotFound(RegistryError, KeyError):
    pass


@dataclass(frozen=True)
class AgentRecord:
    agent_id: str
    name: str
    url: str  # URL base del agente (sin la ruta well-known)
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""

    def __post_init__(self):
        if not _AGENT_ID.match(self.agent_id):
            raise RegistryError(f"agent_id invalido: {self.agent_id!r} (minusculas, digitos, - y _)")
        if not self.url.startswith(("http://", "https://")):
            raise RegistryError(f"url invalida para {self.agent_id}: {self.url!r}")
        object.__setattr__(self, "url", self.url.rstrip("/"))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))

    @property
    def card_url(self) -> str:
        return self.url + AGENT_CARD_WELL_KNOWN_PATH


class AgentRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._agents: dict[str, AgentRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            agents = raw.get("agents") or {}
            self._agents = {
                aid: AgentRecord(agent_id=aid, name=a["name"], url=a["url"],
                                 capabilities=tuple(a.get("capabilities", [])), description=a.get("description", ""))
                for aid, a in agents.items()
            }
        except (yaml.YAMLError, KeyError, TypeError, AttributeError) as exc:
            raise RegistryError(f"Registro invalido en {self.path}: {exc}") from exc

    def _save(self) -> None:
        data = {
            "version": _FORMAT_VERSION,
            "agents": {
                aid: {k: (list(v) if k == "capabilities" else v) for k, v in asdict(r).items() if k != "agent_id"}
                for aid, r in sorted(self._agents.items())
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        tmp.replace(self.path)  # escritura atomica

    # ----------------------------------------------------------------- API
    def register(self, record: AgentRecord, *, overwrite: bool = True) -> AgentRecord:
        with self._lock:
            if not overwrite and record.agent_id in self._agents:
                raise RegistryError(f"{record.agent_id} ya esta registrado")
            self._agents[record.agent_id] = record
            self._save()
        return record

    def resolve(self, agent_id: str) -> AgentRecord:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise AgentNotFound(f"Agente no registrado: {agent_id}") from None

    def find_by_capability(self, capability: str) -> list[AgentRecord]:
        return [r for r in self._agents.values() if capability in r.capabilities]

    def list_capabilities(self) -> dict[str, list[str]]:
        caps: dict[str, list[str]] = {}
        for r in sorted(self._agents.values(), key=lambda r: r.agent_id):
            for c in r.capabilities:
                caps.setdefault(c, []).append(r.agent_id)
        return caps

    def list_agents(self) -> list[AgentRecord]:
        return sorted(self._agents.values(), key=lambda r: r.agent_id)
