import { useState } from "react";
import type { CaseResult } from "./api";

type StepState = "ok" | "warn" | "fail";
type Step = { key: string; title: string; ms: number; state: StepState; headline: string; details: string[] };

const label = (value?: string | null) => (value ?? "").replaceAll("_", " ");
const fmtMs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);
const ICON: Record<StepState, string> = { ok: "✓", warn: "!", fail: "✕" };

function buildSteps(r: CaseResult): Step[] {
  const t = r.tiempos_ms ?? {};
  const validadas = r.obligaciones.filter((o) => o.estado_validacion === "validada").length;
  const propuestas = r.obligaciones.filter((o) => o.estado_validacion === "propuesta").length;
  const citas = Array.from(new Set(r.obligaciones.filter((o) => o.cita).map((o) => `${o.cita!.norma} · Art. ${o.cita!.articulo}`)));
  const claims = r.claims?.length ?? 0;
  const rechazados = r.claims_rechazados?.length ?? 0;
  const audit = r.audit_result;
  const decision = audit?.decision ?? "";
  const auditState: StepState = r.auditoria_error || /block|escalate/i.test(decision) ? "fail" : /warn/i.test(decision) || !audit ? "warn" : "ok";
  const all: Step[] = [
    { key: "validacion_ms", title: "Validación del evento", ms: t.validacion_ms, state: "ok", headline: `${label(r.case.tipo_evento)} · ${label(r.categoria)}`,
      details: [r.evento_descripcion, `Fecha del evento: ${r.case.fecha_evento}`] },
    { key: "compliance_ms", title: "Compliance: obligaciones, plazos y exposición", ms: t.compliance_ms, state: r.sin_fundamento ? "warn" : "ok",
      headline: r.sin_fundamento ? "Sin obligaciones validadas aplicables" : `${validadas} ${validadas === 1 ? "obligación validada" : "obligaciones validadas"}`,
      details: [`${validadas} validadas · ${propuestas} propuestas pendientes de validación`, `${r.plazos.length} plazos calculados · ${r.exposicion.length} exposiciones estimadas`] },
    { key: "rag_ms", title: "Búsqueda normativa (RAG)", ms: t.rag_ms, state: citas.length ? "ok" : "warn",
      headline: citas.length ? `${citas.length} ${citas.length === 1 ? "norma citada" : "normas citadas"}` : "Sin citas recuperadas", details: citas.slice(0, 12) },
    { key: "claims_ms", title: "Armado de afirmaciones verificables", ms: t.claims_ms, state: rechazados ? "warn" : "ok",
      headline: `${claims} ${claims === 1 ? "afirmación" : "afirmaciones"}${rechazados ? ` · ${rechazados} rechazadas` : ""}`,
      details: (r.claims ?? []).slice(0, 8).map((c) => `[${c.type}] ${c.text}`) },
    { key: "resumen_ms", title: "Resumen asistido", ms: t.resumen_ms, state: "ok",
      headline: r.resumen_origen === "llm" ? "Redactado por el modelo (LLM)" : "Plantilla determinista (sin LLM)", details: [r.resumen] },
    { key: "auditoria_ms", title: "Auditoría independiente", ms: t.auditoria_ms, state: auditState,
      headline: r.auditoria_error ? "Error al auditar" : audit ? `${decision}${audit.score != null ? ` · score ${audit.score}` : ""}${audit.risk_level ? ` · riesgo ${audit.risk_level}` : ""}` : "Sin auditoría",
      details: r.auditoria_error ? [r.auditoria_error] : (audit?.findings ?? []).map((f) => `${f.status} · ${f.validator}: ${f.reason}`) },
  ];
  return all.filter((step) => step.ms != null);
}

export function AgentFlow({ result }: { result: CaseResult }) {
  const steps = buildSteps(result);
  const [open, setOpen] = useState<Set<string>>(new Set());
  if (!steps.length) return null;
  const total = result.tiempos_ms.total_ms ?? steps.reduce((sum, s) => sum + s.ms, 0);
  const longest = Math.max(...steps.map((s) => s.ms), 1);
  const toggle = (key: string) => setOpen((prev) => { const next = new Set(prev); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  const allOpen = open.size === steps.length;
  return <article className="panel flow-panel">
    <div className="panel-title">
      <div><h2>Flujo del agente</h2><p>Pasos que ejecutó la evaluación, en orden, con su duración. Tiempo total: <strong>{fmtMs(total)}</strong></p></div>
      <button type="button" className="secondary small" onClick={() => setOpen(allOpen ? new Set() : new Set(steps.map((s) => s.key)))}>{allOpen ? "Contraer todo" : "Expandir todo"}</button>
    </div>
    <ol className="flow">
      {steps.map((step, index) => {
        const isOpen = open.has(step.key);
        return <li key={step.key} className={`flow-step ${step.state}`}>
          <span className="flow-node" aria-hidden>{ICON[step.state]}</span>
          <button type="button" className="flow-head" aria-expanded={isOpen} onClick={() => toggle(step.key)}>
            <span className="flow-main">
              <span className="flow-title"><span className="flow-index">{index + 1}</span>{step.title}</span>
              <span className="flow-headline">{step.headline}</span>
              <span className="flow-bar"><span style={{ width: `${Math.max(4, (step.ms / longest) * 100)}%` }} /></span>
            </span>
            <span className="flow-ms">{fmtMs(step.ms)}</span>
            <span className={`chev big ${isOpen ? "up" : ""}`} aria-hidden>▾</span>
          </button>
          {isOpen && <div className="flow-detail">{step.details.length ? step.details.map((line, i) => <p key={i}>{line}</p>) : <p className="muted">Sin detalle adicional.</p>}</div>}
        </li>;
      })}
    </ol>
  </article>;
}

const STATE_ORDER = ["validada", "propuesta", "no_encontrada", "rechazada"];
const PREVIEW = 5;

export function ObligationList({ items }: { items: CaseResult["obligaciones"] }) {
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const counts = STATE_ORDER.map((state) => [state, items.filter((o) => o.estado_validacion === state).length] as const).filter(([, n]) => n > 0);
  const visible = showAll ? items : items.slice(0, PREVIEW);
  const toggle = (code: string) => setOpen((prev) => { const next = new Set(prev); if (next.has(code)) next.delete(code); else next.add(code); return next; });
  return <div className="oblig">
    <div className="oblig-bar">
      <div className="chips">{counts.map(([state, n]) => <span key={state} className={`chip ${state === "validada" ? "chip-ok" : state === "propuesta" ? "chip-warn" : ""}`}>{n} {label(state)}{n > 1 ? "s" : ""}</span>)}</div>
      <button type="button" className="secondary small" onClick={() => setOpen(open.size ? new Set() : new Set(visible.map((o) => o.codigo)))}>{open.size ? "Contraer todo" : "Expandir visibles"}</button>
    </div>
    <div className="oblig-list">
      {visible.map((item) => {
        const isOpen = open.has(item.codigo);
        const bodyText = [item.sujeto && `${item.sujeto}.`, item.plazo_texto && `Plazo: ${item.plazo_texto}.`, item.cita_textual].filter(Boolean).join(" ");
        return <div key={item.codigo} className={`oblig-item ${item.estado_validacion}`}>
          <button type="button" className="oblig-head" aria-expanded={isOpen} onClick={() => toggle(item.codigo)}>
            <span className="oblig-main">
              <span className="oblig-code"><code>{item.codigo}</code><span className={`chip ${item.estado_validacion === "validada" ? "chip-ok" : item.estado_validacion === "propuesta" ? "chip-warn" : ""}`}>{label(item.estado_validacion)}</span></span>
              <strong className={isOpen ? "" : "oblig-action"}>{item.accion_requerida ?? "Obligación identificada"}</strong>
            </span>
            <span className={`chev big ${isOpen ? "up" : ""}`} aria-hidden>▾</span>
          </button>
          {isOpen && <div className="oblig-body">
            {bodyText && <p>{bodyText}</p>}
            {item.cita && <div className="chips"><span className="chip chip-strong">{item.cita.norma}</span><span className="chip">Art. {item.cita.articulo}</span><span className="chip">Versión {item.cita.version_id}</span><span className="chip">Desde {item.cita.vigente_desde.split("-").reverse().join("/")}</span></div>}
          </div>}
        </div>;
      })}
    </div>
    {items.length > PREVIEW && <button type="button" className="text-toggle" onClick={() => setShowAll(!showAll)}>{showAll ? "Mostrar menos" : `Mostrar las ${items.length - PREVIEW} restantes`}<span className={`chev ${showAll ? "up" : ""}`} aria-hidden>▾</span></button>}
  </div>;
}
