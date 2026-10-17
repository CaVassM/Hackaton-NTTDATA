"""Levanta TODO el backend con un solo comando (Windows / Linux / macOS).

    conda activate hackaton-ntt
    python scripts/start_backend.py                 # verifica, levanta y abre Cloudflare Tunnel
    python scripts/start_backend.py --no-cloudflare # levanta solo en local
    python scripts/start_backend.py --dry-run       # solo verifica (no instala, no levanta)
    python scripts/start_backend.py --reingest      # vuelve a preparar e ingerir la normativa
    python scripts/start_backend.py --reextract     # relanza la extraccion de compliance (background)
    python scripts/start_backend.py --port 8080

Pasos: 1 Python+deps · 2 .env · 3 Ollama+modelos · 4 bases · 5 normativa (rag)
       6 compliance · 7 servidores · 8 /health. Idempotente: si el backend ya
responde en el puerto, no levanta otro. Ctrl+C detiene lo que este script lanzo.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
PY = sys.executable
TOTAL = 8
PLACEHOLDER_TOKEN = "cambia-este-token"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True, write_through=True)


class Falla(Exception):
    def __init__(self, motivo: str, arreglo: str):
        super().__init__(motivo)
        self.motivo, self.arreglo = motivo, arreglo


def paso(n: int, titulo: str) -> None:
    print(f"\n[{n}/{TOTAL}] {titulo}")


def ok(msg: str) -> None:
    print(f"   OK    {msg}")


def warn(msg: str) -> None:
    print(f"   AVISO {msg}")


def info(msg: str) -> None:
    print(f"   ...   {msg}")


def _get_json(url: str, timeout: float = 5.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - solo localhost
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _puerto_ocupado(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _parse_env(path: Path) -> dict[str, str]:
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "si", "sí")


def _count(db: Path, sql: str) -> int | None:
    if not db.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as c:
            return c.execute(sql).fetchone()[0]
    except sqlite3.Error:
        return None


# ------------------------------------------------------------------ pasos
def paso1_python() -> None:
    paso(1, "Python, entorno y dependencias")
    if sys.version_info < (3, 11):
        raise Falla(f"Python {sys.version.split()[0]}: se requiere 3.11+", "conda activate hackaton-ntt")
    env = os.environ.get("CONDA_DEFAULT_ENV") or Path(sys.prefix).name
    ok(f"Python {sys.version.split()[0]} ({env})")
    if env != "hackaton-ntt":
        warn("no estas en el env 'hackaton-ntt' (conda activate hackaton-ntt)")
    faltan, distintas = [], []
    for ln in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?==([^\s#]+)", ln)
        if not m:
            continue
        nombre, ver = m.groups()
        try:
            inst = md.version(nombre)
        except md.PackageNotFoundError:
            faltan.append(f"{nombre}=={ver}")
            continue
        if inst != ver:
            distintas.append(f"{nombre} {inst} (requirements: {ver})")
    if faltan:
        raise Falla(f"faltan dependencias: {', '.join(faltan)}", "pip install -r requirements.txt")
    ok("dependencias de requirements.txt instaladas")
    for d in distintas:
        warn(f"version distinta: {d}")


def paso2_env(env_file: Path, dry: bool) -> dict[str, str]:
    paso(2, f"Archivo de configuracion ({env_file.name})")
    if not env_file.exists():
        if dry:
            warn(f"no existe {env_file}; se crearia desde .env.example")
            env_file = ROOT / ".env.example"
        else:
            shutil.copy(ROOT / ".env.example", env_file)
            ok(f"creado {env_file} desde .env.example (revisa los tokens)")
    vals = _parse_env(env_file)
    for k, v in vals.items():  # los procesos hijos y los settings leen el mismo valor
        os.environ.setdefault(k, v)
    uit = vals.get("UIT_VALOR", "").strip()
    try:
        if float(uit) <= 0:
            raise ValueError
    except ValueError:
        raise Falla("UIT_VALOR falta o no es un numero positivo en el .env",
                    f"agrega a {env_file.name}:  UIT_VALOR=5500   (D.S. N° 301-2025-EF)") from None
    ok(f"UIT_VALOR = {uit}")
    if _bool(vals.get("NANDA_ENABLED")):
        try:
            tokens = json.loads(vals.get("A2A_AGENT_TOKENS") or "{}")
        except ValueError:
            tokens = None
        cliente = vals.get("NANDA_AGENT_TOKEN", "")
        if not tokens or not isinstance(tokens, dict):
            raise Falla("NANDA_ENABLED=true pero A2A_AGENT_TOKENS esta vacio o no es JSON",
                        'en .env:  A2A_AGENT_TOKENS={"copilot": "<token>"}  (python -c "import secrets; print(secrets.token_urlsafe(32))")')
        if PLACEHOLDER_TOKEN in tokens.values() or cliente == PLACEHOLDER_TOKEN or not cliente:
            raise Falla("NANDA_ENABLED=true con token de ejemplo o NANDA_AGENT_TOKEN vacio",
                        "genera un token y ponlo en A2A_AGENT_TOKENS y en NANDA_AGENT_TOKEN")
        if cliente not in tokens.values():
            raise Falla("NANDA_AGENT_TOKEN no coincide con ningun token de A2A_AGENT_TOKENS",
                        "usa el MISMO token en ambas variables")
        ok("agente nanda habilitado; tokens coherentes")
    else:
        ok("agente nanda deshabilitado (NANDA_ENABLED=false)")
    return vals


def paso3_ollama(vals: dict[str, str], dry: bool, warmup: bool) -> None:
    paso(3, "Ollama y modelos")
    host = vals.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    modelos = [vals.get("LLM_MODEL", "qwen3.5:4b"), vals.get("EMBED_MODEL", "qwen3-embedding:0.6b-q8_0")]
    tags = _get_json(f"{host}/api/tags", 3)
    if tags is None:
        if dry:
            warn(f"Ollama no responde en {host}; se intentaria iniciar con 'ollama serve'")
            return
        if not shutil.which("ollama"):
            raise Falla("Ollama no responde y el comando 'ollama' no esta instalado", "instala desde https://ollama.com/download")
        info("Ollama no responde; iniciando 'ollama serve'...")
        LOGS.mkdir(exist_ok=True)
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(["ollama", "serve"], stdout=open(LOGS / "ollama.log", "ab"), stderr=subprocess.STDOUT,
                         creationflags=flags)
        for _ in range(30):
            time.sleep(1)
            if (tags := _get_json(f"{host}/api/tags", 2)) is not None:
                break
        else:
            raise Falla("Ollama no arranco en 30 s", "abre la app de Ollama o ejecuta 'ollama serve' y revisa logs/ollama.log")
    ok(f"Ollama responde en {host}")
    presentes = {m["model"] if ":" in m["model"] else m["model"] + ":latest" for m in tags.get("models", [])}
    for m in modelos:
        mm = m if ":" in m else m + ":latest"
        if mm in presentes:
            ok(f"modelo {m}")
        elif dry:
            warn(f"falta {m}; se ejecutaria 'ollama pull {m}'")
        else:
            info(f"descargando {m} (ollama pull)...")
            if subprocess.run(["ollama", "pull", m]).returncode != 0:
                raise Falla(f"no se pudo descargar {m}", f"ollama pull {m}")
            ok(f"modelo {m} descargado")
    if warmup and not dry:
        t0 = time.time()
        body = json.dumps({"model": modelos[0], "prompt": "Responde solo: ok", "stream": False, "think": False,
                           "options": {"num_predict": 4}, "keep_alive": "30m"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(f"{host}/api/generate", body,  # noqa: S310
                                                          {"Content-Type": "application/json"}), timeout=180).read()
            ok(f"LLM precalentado en {time.time() - t0:.1f} s (queda cargado 30 min)")
        except (urllib.error.URLError, OSError) as exc:
            warn(f"no se pudo precalentar el LLM ({exc}); la primera llamada sera mas lenta")


def _dbs() -> dict[str, Path]:
    p = ROOT / "data" / "processed"
    return {"rag": p / "rag" / "rag.sqlite", "compliance": p / "compliance" / "compliance.sqlite",
            "audit": p / "audit" / "audit.sqlite", "cases": p / "cases" / "cases.sqlite"}


def paso4_bases(dry: bool) -> None:
    paso(4, "Bases SQLite")
    dbs = _dbs()
    if dry:
        for k, db in dbs.items():
            (ok if db.exists() else warn)(f"{k}: {'existe' if db.exists() else 'no existe; se crearia el esquema'} ({db.relative_to(ROOT)})")
        return
    sys.path.insert(0, str(ROOT))
    # Construir el contenedor crea los esquemas que falten (CREATE ... IF NOT EXISTS).
    from app.main import build_container

    build_container()
    for k, db in dbs.items():
        ok(f"{k}: {db.relative_to(ROOT)}")


def paso5_rag(dry: bool, reingest: bool) -> None:
    paso(5, "Normativa (rag)")
    n = _count(_dbs()["rag"], "SELECT COUNT(*) FROM version") or 0
    if n and not reingest:
        ok(f"{n} versiones ingeridas (usa --reingest para volver a preparar e ingerir)")
        return
    motivo = "--reingest" if reingest else "rag vacio"
    if dry:
        warn(f"{motivo}: se ejecutaria prepare_sbs.py + ingesta de data/raw/sbs_txt y data/raw/sinteticos")
        return
    info(f"{motivo}: preparando PDFs SBS (scripts/prepare_sbs.py)...")
    if subprocess.run([PY, str(ROOT / "scripts" / "prepare_sbs.py")], cwd=ROOT).returncode != 0:
        raise Falla("prepare_sbs.py fallo", "python scripts/prepare_sbs.py   (revisa data/raw/sbs/)")
    for carpeta in ("data/raw/sbs_txt", "data/raw/sinteticos"):
        info(f"ingiriendo {carpeta} (embeddings con Ollama)...")
        if subprocess.run([PY, "-m", "modules.rag.cli", "ingest", carpeta], cwd=ROOT,
                          stdout=subprocess.DEVNULL).returncode != 0:
            raise Falla(f"la ingesta de {carpeta} fallo", f"python -m modules.rag.cli ingest {carpeta}")
    ok(f"{_count(_dbs()['rag'], 'SELECT COUNT(*) FROM version')} versiones ingeridas")


def paso6_compliance(dry: bool, reextract: bool) -> None:
    paso(6, "Compliance (propuestas)")
    db = _dbs()["compliance"]
    total = _count(db, "SELECT COUNT(*) FROM obligacion") or 0
    validadas = _count(db, "SELECT COUNT(*) FROM obligacion WHERE estado='validada'") or 0
    pendientes = _count(db, "SELECT COUNT(*) FROM obligacion WHERE estado='propuesta'") or 0
    ok(f"obligaciones: {total} ({validadas} validadas, {pendientes} sin validar)")
    if pendientes:
        warn(f"{pendientes} propuestas siguen SIN VALIDAR (este script no valida nada). "
             "Ver: python -m modules.compliance.cli proposals")
    if total == 0 and not reextract:
        warn("no hay propuestas: lanza la extraccion con --reextract (~8 min con GPU)")
    if not reextract:
        return
    if dry:
        warn("--reextract: se lanzaria la extraccion de obligaciones e infracciones en background")
        return
    LOGS.mkdir(exist_ok=True)
    log = LOGS / f"extract_{time.strftime('%Y%m%d_%H%M%S')}.log"
    code = ("from shared.logging import configure_logging; configure_logging();"
            "from modules.compliance import ComplianceFacade as F; f=F.from_settings();"
            "print(f.extract_obligations()); print(f.extract_infractions())")
    subprocess.Popen([PY, "-c", code], cwd=ROOT, stdout=open(log, "ab"), stderr=subprocess.STDOUT)
    ok(f"extraccion lanzada en background; log: {log.relative_to(ROOT)}")


def paso7_servidores(vals: dict[str, str], port: int, dry: bool) -> list[subprocess.Popen]:
    paso(7, "Servidores")
    procs: list[subprocess.Popen] = []
    nanda = _bool(vals.get("NANDA_ENABLED"))
    a2a_port = int(re.search(r":(\d+)", vals.get("A2A_PUBLIC_URL", "http://localhost:8100").split("//")[-1]).group(1)) \
        if re.search(r":(\d+)", vals.get("A2A_PUBLIC_URL", "http://localhost:8100").split("//")[-1]) else 8100
    plan = [("backend", "app.main:app", port)] + ([("agente nanda (A2A)", "modules.audit.api.app:app", a2a_port)] if nanda else [])
    for nombre, target, p in plan:
        if dry:
            estado = "ocupado (¿ya corre?)" if _puerto_ocupado(p) else "libre"
            info(f"se lanzaria {nombre}: uvicorn {target} --port {p}  [puerto {estado}]")
            continue
        if _puerto_ocupado(p):
            # /health consulta Ollama y verifica la cadena de audit: puede tardar varios segundos.
            if nombre == "backend" and _get_json(f"http://127.0.0.1:{p}/health", 20):
                ok(f"{nombre} ya esta corriendo en el puerto {p}; no se lanza otro")
                continue
            if nombre != "backend" and _get_json(f"http://127.0.0.1:{p}/.well-known/agent-card.json", 3):
                ok(f"{nombre} ya esta corriendo en el puerto {p}")
                continue
            raise Falla(f"el puerto {p} esta ocupado por otro proceso", f"usa --port <otro> o libera el puerto {p}")
        LOGS.mkdir(exist_ok=True)
        log = LOGS / ("backend.log" if nombre == "backend" else "nanda.log")
        procs.append(subprocess.Popen([PY, "-m", "uvicorn", target, "--host", "127.0.0.1", "--port", str(p)],
                                      cwd=ROOT, stdout=open(log, "ab"), stderr=subprocess.STDOUT))
        ok(f"{nombre} lanzado en el puerto {p} (log: {log.relative_to(ROOT)})")
    return procs


def paso8_health(port: int, vals: dict[str, str], dry: bool, procs: list[subprocess.Popen]) -> None:
    paso(8, "Verificacion (/health)")
    base = f"http://localhost:{port}"
    if dry:
        info(f"se consultaria {base}/health")
        return
    h = None
    for _ in range(180):
        if any(p.poll() is not None for p in procs):
            raise Falla("un servidor termino al arrancar", "revisa logs/backend.log y logs/nanda.log")
        if (h := _get_json(f"{base}/health", 5)) is not None:
            break
        time.sleep(1)
    if h is None:
        raise Falla("/health no respondio en 3 min", "revisa logs/backend.log")
    b = h["bases"]
    obl = b["compliance"]["obligaciones"]
    (ok if h["status"] == "ok" else warn)(f"estado: {h['status']}")
    ok(f"Ollama: {'OK' if h['ollama']['reachable'] else 'NO RESPONDE'} {h['ollama']['models']}")
    ok(f"rag: {b['rag']['versiones_sql']} versiones | compliance: {obl.get('validada', 0)} validadas / "
       f"{obl.get('propuesta', 0)} propuestas | audit: {b['audit'].get('auditorias', 0)} auditorias, "
       f"cadena {'OK' if b['audit'].get('cadena_ok') else 'ROTA'} | casos: {sum(b['cases'].get('casos', {}).values())}, expedientes: {sum(b['cases'].get('expedientes', {}).values())}")
    print("\n" + "=" * 64)
    print("  BACKEND LISTO")
    print(f"  API + docs (OpenAPI):  {base}/docs")
    print(f"  Salud:                 {base}/health")
    print(f"  Esquema de casos:      {base}/cases/schema")
    if h["nanda"]["enabled"]:
        print(f"  Agente auditor A2A:    {h['nanda']['agent_card']}  ({'OK' if h['nanda']['reachable'] else 'no responde'})")
    print(f"  Politica de auditoria: {h['policy_version']}  | modo auditoria de casos: {h['audit_mode']}")
    print("  Ctrl+C para detener lo que lanzo este script.")
    print("=" * 64)


def iniciar_cloudflare(port: int) -> tuple[subprocess.Popen, str]:
    """Inicia un Quick Tunnel temporal y devuelve su proceso y URL publica."""
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        raise Falla("no se encontro 'cloudflared'", "instala cloudflared o ejecuta con --no-cloudflare")

    LOGS.mkdir(exist_ok=True)
    log = LOGS / "cloudflared.log"
    with open(log, "wb") as salida:
        proc = subprocess.Popen(
            [cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
            cwd=ROOT, stdout=salida, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )

    url_re = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)
    for _ in range(60):
        if proc.poll() is not None:
            raise Falla(f"cloudflared termino al iniciar (revisa {log.relative_to(ROOT)})",
                        "verifica tu conexion a internet e instalacion de cloudflared")
        try:
            contenido = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            contenido = ""
        if match := url_re.search(contenido):
            url = match.group(0)
            ok(f"URL Cloudflare (API): {url}")
            ok(f"Documentacion publica: {url}/docs")
            ok(f"log del tunnel: {log.relative_to(ROOT)}")
            return proc, url
        time.sleep(1)

    proc.terminate()
    raise Falla(f"no se obtuvo URL de Cloudflare en 60 s (revisa {log.relative_to(ROOT)})",
                "verifica la conexion a internet y el log de cloudflared")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Levanta el backend completo")
    ap.add_argument("--port", type=int, default=int(os.environ.get("API_PORT", 8000)))
    ap.add_argument("--reingest", action="store_true", help="volver a preparar e ingerir la normativa")
    ap.add_argument("--reextract", action="store_true", help="relanzar la extraccion de compliance (background)")
    ap.add_argument("--dry-run", action="store_true", help="solo verificar: no instala, no ingiere, no levanta")
    tunnel = ap.add_mutually_exclusive_group()
    tunnel.add_argument("--cloudflare", "--cloudfare", dest="cloudflare", action="store_true", help=argparse.SUPPRESS)
    tunnel.add_argument("--no-cloudflare", dest="cloudflare", action="store_false",
                        help="no crear Cloudflare Tunnel; dejar el backend solo en localhost")
    ap.set_defaults(cloudflare=True)
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    ap.add_argument("--no-warmup", action="store_true", help="no precalentar el LLM")
    a = ap.parse_args(argv)
    os.chdir(ROOT)
    print(f"Backend Hackaton NTTDATA {'(DRY-RUN: solo verificacion)' if a.dry_run else ''}")
    procs: list[subprocess.Popen] = []
    try:
        paso1_python()
        vals = paso2_env(a.env_file, a.dry_run)
        paso3_ollama(vals, a.dry_run, not a.no_warmup)
        paso4_bases(a.dry_run)
        paso5_rag(a.dry_run, a.reingest)
        paso6_compliance(a.dry_run, a.reextract)
        procs = paso7_servidores(vals, a.port, a.dry_run)
        paso8_health(a.port, vals, a.dry_run, procs)
        if a.cloudflare and not a.dry_run:
            tunnel, _ = iniciar_cloudflare(a.port)
            procs.append(tunnel)
        elif a.cloudflare:
            info(f"se expondria http://127.0.0.1:{a.port} con 'cloudflared tunnel --url'")
    except Falla as f:
        print(f"\n   FALLA  {f.motivo}\n   Para corregir: {f.arreglo}")
        for p in procs:
            p.terminate()
        return 1
    if a.dry_run:
        print("\nDry-run completo: todas las verificaciones obligatorias pasaron.")
        return 0
    if not procs:
        return 0  # todo ya estaba corriendo
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("\nUn servicio se detuvo; revisa logs/backend.log, logs/nanda.log y logs/cloudflared.log")
        for p in procs:
            if p.poll() is None:
                p.terminate()
        return 1
    except KeyboardInterrupt:
        print("\nDeteniendo servicios...")
        for p in procs:
            if p.poll() is None:
                p.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
