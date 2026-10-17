"""Smoke test de scripts/start_backend.py en --dry-run (no levanta servidores)."""
import subprocess
import sys

from shared.config import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "start_backend.py"


def _run(env_file, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args, "--dry-run", "--env-file", str(env_file)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=PROJECT_ROOT)


def test_dry_run_recorre_los_8_pasos(tmp_path):
    env = tmp_path / "ok.env"
    env.write_text((PROJECT_ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    r = _run(env)
    assert r.returncode == 0, r.stdout + r.stderr
    for n in range(1, 9):
        assert f"[{n}/8]" in r.stdout
    assert "Dry-run completo" in r.stdout and "se lanzaria backend" in r.stdout
    assert "se expondria http://127.0.0.1:8000" in r.stdout


def test_no_cloudflare_desactiva_el_tunnel_en_dry_run(tmp_path):
    env = tmp_path / "ok.env"
    env.write_text((PROJECT_ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    r = _run(env, "--no-cloudflare")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "se expondria http://127.0.0.1:8000" not in r.stdout


def test_falla_clara_sin_uit_valor(tmp_path):
    env = tmp_path / "sin_uit.env"
    env.write_text("\n".join(l for l in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
                             if not l.startswith("UIT_VALOR")), encoding="utf-8")
    r = _run(env)
    assert r.returncode == 1 and "UIT_VALOR" in r.stdout and "Para corregir" in r.stdout


def test_falla_con_nanda_y_token_de_ejemplo(tmp_path):
    env = tmp_path / "nanda.env"
    env.write_text((PROJECT_ROOT / ".env.example").read_text(encoding="utf-8") + "\nNANDA_ENABLED=true\n",
                   encoding="utf-8")
    r = _run(env)
    assert r.returncode == 1 and "token de ejemplo" in r.stdout
