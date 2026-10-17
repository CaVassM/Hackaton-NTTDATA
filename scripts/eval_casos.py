"""Evalua el agente contra los resultados esperados del equipo.

    python scripts/eval_casos.py                                   # usa pruebas/*.csv
    python scripts/eval_casos.py --entrada X.csv --esperados Y.csv --persistir

Corre el MISMO flujo que POST /cases/expedientes/batch (en proceso, sin servidor)
y compara campo por campo. Por defecto usa bases temporales (no ensucia la
cadena de auditoria real); --persistir guarda en data/processed.
Salidas: data/processed/eval/resultados_agente.csv y reporte_eval.json.
"""
import argparse
import collections
import csv
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CAMPOS = ["resultado_esperado", "cumple_segun_evidencia", "modalidad_analisis", "norma_a_consultar",
          "alerta_normativa_esperada", "alerta_plazo_interno_esperada", "tipo_alerta_esperada",
          "fecha_registro", "fecha_limite_interna", "fecha_atencion", "dias_de_retraso_interno",
          "prioridad", "sancion_aplicable", "revision_humana"]
# Campos que dependen de fechas internas: si el agente no las tuvo, no son evaluables.
DEPENDEN_DE_FECHAS = {"alerta_plazo_interno_esperada", "tipo_alerta_esperada", "fecha_registro",
                      "fecha_limite_interna", "fecha_atencion", "dias_de_retraso_interno"}


def _facade(persistir: bool):
    from modules.audit import AuditFacade, AuditSettings
    from modules.cases import CasesFacade, CasesSettings
    from modules.rag import RagFacade

    rag = RagFacade.from_settings()
    if persistir:
        return CasesFacade.from_settings(rag=rag, audit=AuditFacade.from_settings(rag=rag), compliance=object())
    tmp = Path(tempfile.mkdtemp(prefix="eval_casos_"))
    audit = AuditFacade.from_settings(AuditSettings(audit_dir=tmp / "audit", log_dir=tmp / "logs"), rag=rag)
    return CasesFacade.from_settings(CasesSettings(cases_dir=tmp / "cases", log_dir=tmp / "logs", cases_summary_llm=False),
                                     rag=rag, audit=audit, compliance=object())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", type=Path, default=ROOT / "pruebas" / "casos_para_validacion_agente.csv")
    ap.add_argument("--esperados", type=Path, default=ROOT / "pruebas" / "resultados_esperados_casos_rag_detallados.csv")
    ap.add_argument("--salida", type=Path, default=ROOT / "data" / "processed" / "eval")
    ap.add_argument("--persistir", action="store_true")
    a = ap.parse_args(argv)

    from shared.logging import configure_logging

    configure_logging("WARNING")
    f = _facade(a.persistir)
    t0 = time.perf_counter()
    items = f.expedientes_batch(f.parse_expedientes_csv(a.entrada.read_text(encoding="utf-8-sig")))
    seg = time.perf_counter() - t0
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "resultados_agente.csv").write_text(f.expedientes_a_csv(items), encoding="utf-8-sig")

    esperados = {r["id_caso"]: r for r in csv.DictReader(a.esperados.open(encoding="utf-8-sig"))}
    agente = {i["id_caso"]: i["result"].as_row() for i in items if i["ok"]}
    errores = [i for i in items if not i["ok"]]

    stats = {c: collections.Counter() for c in CAMPOS}
    conf = collections.Counter()
    fallos = collections.defaultdict(list)
    for cid, exp in esperados.items():
        got = agente.get(cid)
        if got is None:
            continue
        sin_fechas = got["alerta_plazo_interno_esperada"] == "NO_DETERMINABLE"
        conf[(exp["resultado_esperado"], got["resultado_esperado"])] += 1
        for c in CAMPOS:
            if c in DEPENDEN_DE_FECHAS and sin_fechas:
                stats[c]["no_evaluable"] += 1
            elif got[c].strip() == exp[c].strip():
                stats[c]["ok"] += 1
            else:
                stats[c]["fallo"] += 1
                if len(fallos[c]) < 5:
                    fallos[c].append({"id_caso": cid, "esperado": exp[c], "agente": got[c]})

    posibles = sum(v for (e, _), v in conf.items() if e == "POSIBLE_INCUMPLIMIENTO")
    fn = sum(v for (e, g), v in conf.items() if e == "POSIBLE_INCUMPLIMIENTO" and g == "SIN_INCUMPLIMIENTO_DETECTADO")
    fp = sum(v for (e, g), v in conf.items() if e == "SIN_INCUMPLIMIENTO_DETECTADO" and g == "POSIBLE_INCUMPLIMIENTO")
    decisiones = collections.Counter(r["decision_auditoria"] for r in agente.values())
    reporte = {
        "casos": len(esperados), "procesados": len(agente), "errores": len(errores), "segundos": round(seg, 2),
        "por_campo": {c: {**s, "acierto_sobre_evaluables": round(s["ok"] / max(1, s["ok"] + s["fallo"]), 4)}
                      for c, s in stats.items()},
        "matriz_resultado": {f"{e} -> {g}": v for (e, g), v in sorted(conf.items())},
        "falsos_negativos_criticos": fn, "falsos_positivos": fp, "posibles_esperados": posibles,
        "decisiones_auditoria": dict(decisiones), "ejemplos_de_fallo": fallos,
    }
    (a.salida / "reporte_eval.json").write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Evaluacion: {len(agente)}/{len(esperados)} casos en {seg:.1f} s ({len(errores)} errores)\n")
    print(f"{'campo':34} {'ok':>4} {'fallo':>6} {'no_eval':>8} {'acierto':>8}")
    for c, s in stats.items():
        print(f"{c:34} {s['ok']:>4} {s['fallo']:>6} {s['no_evaluable']:>8} {reporte['por_campo'][c]['acierto_sobre_evaluables']:>8.1%}")
    print("\nResultado (esperado -> agente):")
    for k, v in reporte["matriz_resultado"].items():
        print(f"   {v:>4}  {k}")
    print(f"\nFalsos negativos criticos (POSIBLE esperado -> SIN detectado): {fn}   Falsos positivos: {fp}")
    print(f"Decisiones del auditor: {dict(decisiones)}")
    print(f"\nCSV del agente: {(a.salida / 'resultados_agente.csv').relative_to(ROOT)} | reporte: {(a.salida / 'reporte_eval.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
