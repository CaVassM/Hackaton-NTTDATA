import { Fragment, ReactNode, useState } from "react";
import { ClampedText } from "./ResultCards";
import type { CaseResult, ExpedienteResult } from "./api";

type StepState = "ok" | "warn" | "fail";
export type Step = { key: string; title: string; ms?: number; state: StepState; headline: string; details: string[]; body?: ReactNode };

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

export function FlowTimeline({ steps, totalMs, subtitle }: { steps: Step[]; totalMs?: number; subtitle: string }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  if (!steps.length) return null;
  const timed = steps.filter((s) => s.ms != null);
  const longest = Math.max(...timed.map((s) => s.ms as number), 1);
  const toggle = (key: string) => setOpen((prev) => { const next = new Set(prev); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  const allOpen = open.size === steps.length;
  return <article className="panel flow-panel">
    <div className="panel-title">
      <div><h2>Flujo del agente</h2><p>{subtitle}{totalMs != null && <> Tiempo total: <strong>{fmtMs(totalMs)}</strong></>}</p></div>
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
              {step.ms != null && <span className="flow-bar"><span style={{ width: `${Math.max(4, (step.ms / longest) * 100)}%` }} /></span>}
            </span>
            {step.ms != null && <span className="flow-ms">{fmtMs(step.ms)}</span>}
            <span className={`chev big ${isOpen ? "up" : ""}`} aria-hidden>▾</span>
          </button>
          {isOpen && <div className="flow-detail">{step.body ?? (step.details.length ? step.details.map((line, i) => <p key={i}>{line}</p>) : <p className="muted">Sin detalle adicional.</p>)}</div>}
        </li>;
      })}
    </ol>
  </article>;
}

export function AgentFlow({ result }: { result: CaseResult }) {
  const steps = buildSteps(result);
  const total = result.tiempos_ms.total_ms ?? steps.reduce((sum, s) => sum + (s.ms ?? 0), 0);
  return <FlowTimeline steps={steps} totalMs={total} subtitle="Pasos que ejecutó la evaluación, en orden, con su duración." />;
}

// ---------- Formato legible de valores crudos ----------
const DATE_RX = /^\d{4}-\d{2}-\d{2}$/;
const sentence = (v: string) => { const t = v.replaceAll("_", " ").trim().toLowerCase(); return t.charAt(0).toUpperCase() + t.slice(1); };
export function pretty(value: unknown): string {
  if (value == null || value === "") return "";
  const v = String(value);
  if (DATE_RX.test(v)) return v.split("-").reverse().join("/");
  if (v === "SI") return "Sí";
  if (/^[A-ZÁÉÍÓÚÑ0-9_]+$/.test(v) && /[A-Z]{3,}/.test(v)) return sentence(v);
  return v;
}
const txt = (value: unknown) => pretty(value);

type Tone = "ok" | "warn" | "bad" | "info" | "neutral";
const toneOf = (v: unknown): Tone => {
  const t = String(v ?? "").toUpperCase();
  if (/^(ALLOW|PASS|SI|NO_DETECT|SIN_INCUMPLIMIENTO|CUMPLE|OK)/.test(t)) return t === "SI" ? "bad" : "ok";
  if (/(BLOCK|FAIL|ESCALATE|ALTA|POSIBLE_INCUMPLIMIENTO|VENCID)/.test(t)) return "bad";
  if (/(WARN|PENDIENTE|MEDIA|INSUFICIENTE|NO_DETERMIN)/.test(t)) return "warn";
  return "neutral";
};
export function Tag({ children, tone = "neutral", mono = false }: { children: ReactNode; tone?: Tone; mono?: boolean }) {
  return <span className={`tag ${tone} ${mono ? "mono" : ""}`}>{children}</span>;
}
function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="kv-row"><span>{label}</span><div>{children}</div></div>;
}
export function Callout({ tone = "info", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return <div className={`callout ${tone}`}>{title && <b>{title}</b>}<div>{children}</div></div>;
}
const shortId = (id: unknown) => { const v = String(id ?? ""); return v.length > 14 ? `${v.slice(0, 8)}…${v.slice(-4)}` : v; };

function DateTrack({ f }: { f: Record<string, unknown> }) {
  const items: Array<[string, unknown]> = [["Registro", f.fecha_registro], ["Límite interno", f.fecha_limite_interna], ["Atención", f.fecha_atencion]];
  const dias = f.dias_de_retraso_interno == null ? null : Number(f.dias_de_retraso_interno);
  return <div className="date-track">
    {items.map(([label, value], i) => <Fragment key={label}>
      <div className={`date-node ${value ? "" : "empty"}`}><span className="dot" /><small>{label}</small><b>{pretty(value) || "—"}</b></div>
      {i < items.length - 1 && <span className="date-line" />}
    </Fragment>)}
    {dias != null && <Tag tone={dias > 0 ? "bad" : "ok"}>{dias > 0 ? `+${dias} días de atraso` : "En plazo"}</Tag>}
  </div>;
}

type FindingLike = { validator: string; status: string; reason: string };
export function Findings({ findings }: { findings: FindingLike[] }) {
  const groups = new Map<string, { item: FindingLike; n: number }>();
  findings.forEach((x) => { const k = `${x.status}|${x.validator}|${x.reason}`; const g = groups.get(k); if (g) g.n += 1; else groups.set(k, { item: x, n: 1 }); });
  const list = Array.from(groups.values()).sort((x, y) => (x.item.status === "PASS" ? 1 : 0) - (y.item.status === "PASS" ? 1 : 0));
  if (!list.length) return <p className="muted">Sin hallazgos del auditor.</p>;
  return <ul className="findings">
    {list.map(({ item, n }, i) => <li key={i}>
      <Tag tone={toneOf(item.status)}>{item.status}</Tag>
      <Tag mono>{item.validator}</Tag>
      <span>{item.reason}</span>
      {n > 1 && <em>×{n}</em>}
    </li>)}
  </ul>;
}

function buildExpedienteSteps(r: ExpedienteResult): Step[] {
  const f = r.fila;
  const outcome = String(f.resultado_esperado ?? "");
  const senales = String(f.senales_detectadas ?? "").split("|").filter(Boolean);
  const audit = r.audit_result as { decision?: string; score?: number; risk_level?: string; findings?: FindingLike[] } | null | undefined;
  const decision = String(audit?.decision ?? f.decision_auditoria ?? "SIN_AUDITORIA");
  const auditState: StepState = r.auditoria_error || /block|escalate/i.test(decision) ? "fail" : decision === "ALLOW" ? "ok" : "warn";
  const dias = f.dias_de_retraso_interno;
  const plazoState: StepState = f.alerta_plazo_interno_esperada === "SI" || f.alerta_plazo_interno_esperada === "NO_DETERMINABLE" ? "warn" : "ok";
  const sinCorpus = String(f.fuente_legal ?? "").includes("NO_DISPONIBLE");
  return [
    { key: "lectura", title: "Lectura del expediente", state: "ok", headline: `Expediente ${f.id_caso ?? ""}`, details: [],
      body: <div className="flow-rich"><ClampedText className="quote" text={String(f.hechos_relevantes_del_caso ?? "Sin hechos registrados.")} lines={3} />
        <div className="chips"><Tag>Registro: {pretty(f.fecha_registro) || "—"}</Tag><Tag>Límite: {pretty(f.fecha_limite_interna) || "—"}</Tag><Tag>Atención: {pretty(f.fecha_atencion) || "—"}</Tag></div></div> },
    { key: "clasificacion", title: "Clasificación por señales (reglas deterministas)", state: outcome === "POSIBLE_INCUMPLIMIENTO" ? "fail" : outcome === "SIN_INCUMPLIMIENTO_DETECTADO" ? "ok" : "warn",
      headline: `${txt(outcome) || "Sin resultado"} · ${senales.length} ${senales.length === 1 ? "señal" : "señales"}`, details: [],
      body: <div className="flow-rich"><div className="chips">{senales.length ? senales.map((x) => <Tag key={x} tone="warn">{sentence(x)}</Tag>) : <Tag>Sin señales reconocibles</Tag>}{f.reglas_version ? <Tag mono>reglas {String(f.reglas_version)}</Tag> : null}</div>
        <ClampedText text={String(f.por_que_si_o_no ?? "")} lines={2} /></div> },
    { key: "norma", title: "Contraste con la norma", state: sinCorpus ? "warn" : "ok", headline: String(f.norma_a_consultar ?? "Sin norma consultada"), details: [],
      body: <div className="flow-rich"><div className="chips">{f.fuente_legal ? <Tag tone="info">{String(f.fuente_legal)}</Tag> : null}{f.modalidad_analisis ? <Tag>Modalidad: {sentence(String(f.modalidad_analisis))}</Tag> : null}</div>
        <ClampedText text={String(f.razon_de_aplicacion_normativa ?? "")} lines={2} /></div> },
    { key: "plazo", title: "Plazo interno", state: plazoState, headline: dias == null ? "No determinable" : Number(dias) > 0 ? `Atraso de ${dias} días` : "Dentro del plazo", details: [],
      body: <div className="flow-rich"><DateTrack f={f} /><ClampedText text={String(f.explicacion_plazo ?? "")} lines={2} /></div> },
    { key: "auditoria", title: "Auditoría independiente", state: auditState,
      headline: r.auditoria_error ? "Error al auditar" : `${decision}${audit?.score != null ? ` · score ${audit.score}` : ""}${audit?.risk_level ? ` · riesgo ${audit.risk_level}` : ""}`, details: [],
      body: r.auditoria_error ? <Callout tone="bad" title="La auditoría falló">{r.auditoria_error}</Callout>
        : <div className="flow-rich"><Findings findings={audit?.findings ?? []} />{f.audit_id ? <div className="chips"><Tag mono>ID {shortId(f.audit_id)}</Tag></div> : null}</div> },
    { key: "revision", title: "Revisión humana", state: String(f.revision_humana ?? "PENDIENTE") === "PENDIENTE" ? "warn" : "ok", headline: txt(f.revision_humana ?? "PENDIENTE"), details: [],
      body: <Callout tone="warn" title="Pendiente de un revisor">{String(f.limitacion_de_la_evaluacion ?? "La clasificación requiere revisión humana.")}</Callout> },
  ];
}

export function ExpedienteFlow({ result }: { result: ExpedienteResult }) {
  return <FlowTimeline steps={buildExpedienteSteps(result)} totalMs={result.tiempos_ms?.total_ms}
    subtitle="Etapas del análisis del expediente importado. Las reglas son deterministas, por eso solo se mide el tiempo total." />;
}

/** Las cuatro tarjetas de detalle, con jerarquía visual en lugar de volcado de campos. */
export function ExpedienteSections({ result }: { result: ExpedienteResult }) {
  const f = result.fila;
  const audit = result.audit_result as { decision?: string; score?: number; risk_level?: string } | null | undefined;
  const decision = String(audit?.decision ?? f.decision_auditoria ?? "SIN_AUDITORIA");
  const senales = String(f.senales_detectadas ?? "").split("|").filter(Boolean);
  const sancion = String(f.sancion_aplicable ?? "");
  return <div className="two-col wide-left exp-sections">
    <article className="panel">
      <div className="panel-title"><h2>Hechos y evidencia</h2><Tag tone={toneOf(f.cumple_segun_evidencia)}>{pretty(f.cumple_segun_evidencia) || "Sin evaluar"}</Tag></div>
      <ClampedText className="quote" text={String(f.hechos_relevantes_del_caso ?? "Sin hechos registrados.")} lines={5} />
      {f.evidencia_o_faltantes ? <Callout tone="info" title="Evidencia y faltantes por revisar">{String(f.evidencia_o_faltantes)}</Callout> : null}
      {f.por_que_si_o_no ? <div className="sub-block"><h4>Fundamento de la evaluación</h4><ClampedText text={String(f.por_que_si_o_no)} lines={3} /></div> : null}
    </article>
    <article className="panel">
      <div className="panel-title"><h2>Norma y fundamento</h2></div>
      <div className="norm-card"><small>Norma consultada</small><strong>{String(f.norma_a_consultar ?? "—")}</strong>
        <div className="chips">{f.fuente_legal ? <Tag tone="info">{String(f.fuente_legal)}</Tag> : null}{f.version_id_citada ? <Tag mono>versión {String(f.version_id_citada)}</Tag> : null}</div></div>
      {f.razon_de_aplicacion_normativa ? <div className="sub-block"><h4>Aplicación al caso</h4><ClampedText text={String(f.razon_de_aplicacion_normativa)} lines={3} /></div> : null}
      {sancion ? <Callout tone="warn" title="Sanción aplicable">{sancion.startsWith("NO_DETERMINADA") ? "No determinada: requiere decisión judicial; no se deriva automáticamente." : sancion}</Callout> : null}
    </article>
    <article className="panel">
      <div className="panel-title"><h2>Fechas y alertas internas</h2><Tag tone={toneOf(f.prioridad)}>Prioridad {pretty(f.prioridad) || "—"}</Tag></div>
      <DateTrack f={f} />
      <div className="alert-grid">
        <div><small>Alerta normativa</small><Tag tone={f.alerta_normativa_esperada === "SI" ? "bad" : "ok"}>{pretty(f.alerta_normativa_esperada) || "—"}</Tag></div>
        <div><small>Alerta de plazo interno</small><Tag tone={f.alerta_plazo_interno_esperada === "SI" ? "bad" : f.alerta_plazo_interno_esperada === "NO" ? "ok" : "warn"}>{pretty(f.alerta_plazo_interno_esperada) || "—"}</Tag></div>
        <div><small>Tipo de alerta</small><Tag>{pretty(f.tipo_alerta_esperada) || "—"}</Tag></div>
      </div>
      {f.explicacion_plazo ? <ClampedText text={String(f.explicacion_plazo)} lines={3} /> : null}
    </article>
    <article className="panel">
      <div className="panel-title"><h2>Auditoría y revisión humana</h2><Tag tone={toneOf(decision)}>{decision}</Tag></div>
      <div className="kv">
        <Row label="Revisión humana"><Tag tone={toneOf(f.revision_humana)}>{pretty(f.revision_humana) || "—"}</Tag></Row>
        {audit?.score != null && <Row label="Score de riesgo"><b>{audit.score}</b> / 100{audit.risk_level ? <> · riesgo {audit.risk_level}</> : null}</Row>}
        <Row label="ID de auditoría">{f.audit_id ? <Tag mono>{shortId(f.audit_id)}</Tag> : "—"}</Row>
        <Row label="Señales detectadas"><div className="chips">{senales.length ? senales.map((x) => <Tag key={x} tone="warn">{sentence(x)}</Tag>) : "—"}</div></Row>
        <Row label="Reglas"><Tag mono>{String(f.reglas_version ?? "—")}</Tag>{f.modalidad_analisis ? <Tag>{sentence(String(f.modalidad_analisis))}</Tag> : null}</Row>
      </div>
      {f.limitacion_de_la_evaluacion ? <Callout tone="neutral" title="Limitación de la evaluación">{String(f.limitacion_de_la_evaluacion)}</Callout> : null}
    </article>
  </div>;
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
