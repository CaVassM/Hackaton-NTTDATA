import { CSSProperties, ReactNode, useEffect, useMemo, useState } from "react";
import { AgentsInfo, AuditEvent, AuditTrace, Health, RegisteredAgent, api } from "./api";
import { Callout, Findings, Tag } from "./CaseParts";
import { ClampedText } from "./ResultCards";
import "./agents.css";

// Todo lo que se muestra sale de /agents, /audit/events y /audit/{id}/trace:
// nada se simula. Los pasos "protocolo" son los que el cliente nanda ejecuta
// por diseno antes de cada envio y no quedan registrados por separado.

type Tone = "ok" | "warn" | "bad";
type Msg = { from: number; to: number; title: string; kind: "sellado" | "protocolo" | "en proceso"; tone?: Tone; body: ReactNode };

const AUDIT_SKILL = "audit_candidate_response";
const short = (v?: string | number | null, n = 8) => { const s = String(v ?? ""); return s.length > n * 2 ? `${s.slice(0, n)}…${s.slice(-4)}` : s || "—"; };
const fmtTs = (iso: string) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("es-PE", { dateStyle: "short", timeStyle: "medium" }); };
const expedienteDe = (interactionId: string) => interactionId.match(/^(.*)-[0-9a-f]{8}$/)?.[1] ?? interactionId;
const decisionTone = (d?: string): Tone => (d === "ALLOW" ? "ok" : d === "WARN" ? "warn" : "bad");
const auditorDe = (info: AgentsInfo | null) => info?.registro.agentes.find((a) => a.capabilities.includes(AUDIT_SKILL)) ?? null;

function KV({ items }: { items: Array<[string, ReactNode]> }) {
  return <dl className="ag-kv">{items.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

function buildMessages(t: AuditTrace, auditor: RegisteredAgent | null): { lanes: string[]; msgs: Msg[] } {
  const a2a = t.canal === "a2a";
  const res = t.record.result;
  const claims = t.request.candidate.claims;
  const porTipo = claims.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.type]: (acc[c.type] ?? 0) + 1 }), {});
  const evalEvent = t.eventos.find((e) => e.action === "audit.evaluate");
  const reviews = t.eventos.filter((e) => e.action === "audit.review");
  const tr = t.transporte;
  const lanes = a2a ? ["Copiloto · cases", "Registro NANDA", "Auditor · A2A", "Cadena de hashes"] : ["Copiloto · cases", "Auditor · en proceso", "Cadena de hashes"];
  const [COP, REG, AUD, CAD] = a2a ? [0, 1, 2, 3] : [0, -1, 1, 2];
  const criticos = res.findings.filter((f) => f.critical).length;

  const msgs: Msg[] = [{
    from: COP, to: COP, title: "Arma la solicitud de auditoría", kind: "sellado", tone: "ok",
    body: <>
      <KV items={[["Interacción", <code key="i">{t.interaction_id}</code>], ["Caso de uso", t.request.use_case], ["Rol / usuario", `${t.request.role} · ${t.request.user_id}`], ["Afirmaciones", Object.entries(porTipo).map(([k, n]) => `${n} ${k}`).join(" · ")]]} />
      <ul className="ag-claims">{claims.map((c) => <li key={c.claim_id}><Tag mono>{c.claim_id}</Tag><Tag tone={c.type === "normativa" ? "info" : "neutral"}>{c.type}</Tag><span>{c.text}</span>{c.evidence_ids.length > 0 && <Tag mono>versión {c.evidence_ids.join(", ")}</Tag>}</li>)}</ul>
    </>,
  }];

  if (a2a && tr) {
    msgs.push(
      { from: COP, to: REG, title: `Busca quién ofrece «${tr.skill}»`, kind: "protocolo", tone: "ok",
        body: <KV items={[["Capacidad", <code key="c">{tr.skill}</code>], ["Resuelve a", auditor ? <span key="a"><b>{auditor.agent_id}</b> · <code>{auditor.url}</code></span> : "agente auditor registrado"], ["Registro", "nanda/registry.yaml (índice local tipo NANDA)"]]} /> },
      { from: COP, to: AUD, title: "Lee la Agent Card (descubrimiento)", kind: "protocolo", tone: "ok",
        body: <KV items={[["GET", <code key="g">{auditor?.card_url ?? "/.well-known/agent-card.json"}</code>], ["Valida", `skill ${tr.skill} + interfaz ${tr.binding} A2A ${tr.version}`], ["Nota", "El cliente cachea la card por proceso: se descarga una vez y se reutiliza."]]} /> },
      { from: COP, to: AUD, title: `${tr.metodo} · JSON-RPC 2.0`, kind: "sellado", tone: "ok",
        body: <KV items={[["Protocolo", `${tr.protocolo} ${tr.version} · binding ${tr.binding}`], ["Autenticación", `Bearer (token del agente «${tr.agente_declarado ?? "?"}»)`], ["jsonrpc id", <code key="j">{String(tr.jsonrpc_id ?? "—")}</code>], ["messageId", <code key="m">{tr.message_id}</code>], ["contextId", <code key="x">{tr.context_id ?? "—"}</code>], ["DataPart", `AuditRequest con ${claims.length} ${claims.length === 1 ? "afirmación" : "afirmaciones"}`]]} /> },
      { from: AUD, to: AUD, title: "Autentica y autoriza al copiloto", kind: "sellado", tone: tr.agente_declarado && tr.agente_declarado !== tr.agente_autenticado ? "warn" : "ok",
        body: <KV items={[["Token pertenece a", <b key="a">{tr.agente_autenticado}</b>], ["Agente declarado", tr.agente_declarado ?? "—"], ["Coinciden", tr.agente_declarado === tr.agente_autenticado ? "Sí" : "No"], ["Autorización", "Agente en la lista A2A_ALLOWED_AGENTS (si no, 403 antes de evaluar)"]]} /> },
    );
  } else {
    msgs.push({ from: COP, to: AUD, title: "Llamada en proceso (AuditFacade.evaluate)", kind: "en proceso", tone: "warn",
      body: <Callout tone="warn" title="Sin mensaje A2A">Esta auditoría se pidió dentro del mismo proceso (solicitante «{t.solicitado_por ?? "?"}»), sin red ni Agent Card. Para que el copiloto hable con el auditor por A2A: NANDA_ENABLED=true y CASES_AUDIT_MODE=a2a.</Callout> });
  }

  msgs.push(
    { from: AUD, to: AUD, title: `Valida afirmación por afirmación · ${res.findings.length} hallazgos`, kind: "sellado", tone: criticos ? "bad" : res.findings.some((f) => f.status !== "PASS") ? "warn" : "ok",
      body: <Findings findings={res.findings} /> },
    { from: AUD, to: AUD, title: `Decide: ${res.decision} · score ${res.score}`, kind: "sellado", tone: decisionTone(res.decision),
      body: <KV items={[["Decisión", <Tag key="d" tone={decisionTone(res.decision)}>{res.decision}</Tag>], ["Riesgo", res.risk_level], ["Política", <code key="p">{res.policy_version}</code>], ["Motivo", String(res.checks?.decision_reason ?? "—")], ["Requiere humano", res.checks?.requires_human_approval ? "Sí" : "No"], ["Vigencia evaluada", res.effective_date]]} /> },
  );
  if (evalEvent) {
    msgs.push({ from: AUD, to: CAD, title: `Sella el evento #${evalEvent.id}`, kind: "sellado", tone: evalEvent.hash_verificado && evalEvent.resultado_verificado ? "ok" : "bad",
      body: <KV items={[["Actor", evalEvent.actor], ["Fecha", fmtTs(evalEvent.ts)], ["prev_hash", <code key="p">{short(evalEvent.prev_hash, 12)}</code>], ["hash", <code key="h">{short(evalEvent.hash, 12)}</code>], ["Hash recalculado", evalEvent.hash_verificado ? "✓ coincide" : "✕ NO coincide"], ["Digest del resultado", evalEvent.resultado_verificado ? "✓ coincide" : "✕ NO coincide"], ...(a2a ? [["Incluye", "metadatos del mensaje A2A (no editables sin romper la cadena)"] as [string, ReactNode]] : [])]} /> });
  }
  if (a2a && tr) {
    msgs.push({ from: AUD, to: COP, title: "Responde con el AuditResult", kind: "sellado", tone: decisionTone(res.decision),
      body: <KV items={[["Mensaje", "Message ROLE_AGENT · DataPart AuditResult + TextPart resumen"], ["messageId respuesta", <code key="r">{tr.respuesta_message_id}</code>], ["En respuesta a", <code key="q">{tr.message_id}</code>], ["audit_id", <code key="a">{t.audit_id}</code>]]} /> });
  } else {
    msgs.push({ from: AUD, to: COP, title: "Devuelve el AuditResult (en memoria)", kind: "en proceso", tone: decisionTone(res.decision),
      body: <KV items={[["audit_id", <code key="a">{t.audit_id}</code>], ["Decisión", res.decision]]} /> });
  }
  reviews.forEach((e) => msgs.push({ from: CAD, to: CAD, title: `Revisión humana: ${e.payload.decision} · ${e.actor}`, kind: "sellado", tone: e.hash_verificado ? "ok" : "bad",
    body: <KV items={[["Revisor", e.actor], ["Fecha", fmtTs(e.ts)], ["Evento", `#${e.id}`], ["Hash recalculado", e.hash_verificado ? "✓ coincide" : "✕ NO coincide"]]} /> }));
  return { lanes, msgs };
}

export function AgentConversation({ auditId, agents }: { auditId: string; agents?: AgentsInfo | null }) {
  const [trace, setTrace] = useState<AuditTrace | null>(null);
  const [info, setInfo] = useState<AgentsInfo | null>(agents ?? null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set());

  useEffect(() => {
    let alive = true;
    setTrace(null); setError(null); setOpen(new Set());
    api.auditTrace(auditId).then((t) => { if (alive) setTrace(t); }).catch((e: Error) => { if (alive) setError(e.message); });
    if (!agents) api.agents().then((a) => { if (alive) setInfo(a); }).catch(() => undefined);
    return () => { alive = false; };
  }, [auditId, agents]);

  if (error) return <article className="panel ag-conv"><Callout tone="bad" title="No se pudo leer la traza">{error}</Callout></article>;
  if (!trace) return <article className="panel ag-conv"><p className="muted">Leyendo la traza de la auditoría…</p></article>;

  const { lanes, msgs } = buildMessages(trace, auditorDe(info));
  const allOpen = open.size === msgs.length;
  const toggle = (i: number) => setOpen((prev) => { const next = new Set(prev); if (next.has(i)) next.delete(i); else next.add(i); return next; });
  const a2a = trace.canal === "a2a";
  return <article className="panel ag-conv">
    <div className="panel-title">
      <div>
        <h2>Conversación entre agentes</h2>
        <p>{a2a ? "El copiloto pidió la auditoría al agente auditor por A2A. Cada paso marcado «sellado» se lee del registro encadenado del auditor." : "Esta auditoría no pasó por A2A: se resolvió dentro del mismo proceso."} {fmtTs(trace.solicitado_en)}</p>
      </div>
      <div className="ag-head-actions">
        <Tag tone={a2a ? "ok" : "warn"}>{a2a ? `A2A ${trace.transporte?.version ?? ""}` : "en proceso"}</Tag>
        <button type="button" className="secondary small" onClick={() => setOpen(allOpen ? new Set() : new Set(msgs.map((_, i) => i)))}>{allOpen ? "Contraer todo" : "Expandir todo"}</button>
      </div>
    </div>
    <div className="seq" style={{ "--lanes": lanes.length } as CSSProperties}>
      <div className="seq-lanes" aria-hidden>{lanes.map((l, i) => <div key={l} className={`seq-lane-head lane-${a2a ? i : [0, 2, 3][i]}`}><span>{l}</span></div>)}</div>
      <ol className="seq-body">
        {msgs.map((m, i) => {
          const a = Math.min(m.from, m.to), b = Math.max(m.from, m.to);
          const dir = m.from === m.to ? `self${m.from === 0 ? " first" : m.from === lanes.length - 1 ? " last" : ""}` : m.to > m.from ? "right" : "left";
          const isOpen = open.has(i);
          return <li key={i} className="seq-row">
            <div className={`seq-arrow ${dir} ${m.tone ?? "ok"}`} style={{ gridColumn: `${a + 1} / ${b + 2}`, "--span": b - a + 1 } as CSSProperties}>
              <button type="button" aria-expanded={isOpen} onClick={() => toggle(i)}>
                <span className="seq-n">{i + 1}</span>
                <span className="seq-text"><b>{m.title}</b><small>{lanes[m.from]}{m.from !== m.to ? ` → ${lanes[m.to]}` : ""}</small></span>
                <span className={`seq-kind ${m.kind.replace(" ", "-")}`}>{m.kind}</span>
              </button>
            </div>
            {isOpen && <div className="seq-detail">{m.body}</div>}
          </li>;
        })}
      </ol>
    </div>
    <p className="ag-legend"><span className="seq-kind sellado">sellado</span> leído del registro append-only del auditor (incluido en la cadena de hashes) · <span className="seq-kind protocolo">protocolo</span> paso que el cliente nanda ejecuta por diseño antes de enviar; no se registra aparte{!a2a && <> · <span className="seq-kind en-proceso">en proceso</span> llamada local sin red</>}.</p>
    {trace.record.result.safe_response && <ClampedText className="ag-safe" text={`Respuesta segura del auditor: ${trace.record.result.safe_response}`} lines={2} />}
  </article>;
}

function AgentCardBox({ agent }: { agent: RegisteredAgent | null }) {
  const card = agent?.card;
  const itf = card?.supportedInterfaces?.[0];
  const skill = card?.skills?.find((s) => s.id === AUDIT_SKILL) ?? card?.skills?.[0];
  return <div className="ag-agent auditor">
    <div className="ag-agent-top"><span className="ag-avatar">A</span><div><b>{card?.name ?? agent?.name ?? "Auditor"}</b><small>Agente auditor · {agent?.agent_id ?? "sin registrar"}</small></div><Tag tone={agent?.reachable ? "ok" : "bad"}>{agent?.reachable ? "en línea" : "sin respuesta"}</Tag></div>
    {card ? <KV items={[["Agent Card", <code key="c">{agent!.card_url}</code>], ["Interfaz", itf ? `${itf.protocolBinding} · A2A ${itf.protocolVersion}` : "—"], ["Endpoint", <code key="u">{itf?.url ?? "—"}</code>], ["Skill", skill ? `${skill.id} — ${skill.name}` : "—"], ["Seguridad", Object.keys(card.securitySchemes ?? {}).join(", ") || "—"], ["Versión", card.version]]} />
      : <p className="muted">{agent ? `No respondió en ${agent.card_url}. ${agent.error ?? ""}` : "No hay agente con la capacidad audit_candidate_response en el registro."}</p>}
  </div>;
}

export default function AgentsPage({ health, onOpenExpediente }: { health: Health | null; onOpenExpediente: (id: string) => void }) {
  const [info, setInfo] = useState<AgentsInfo | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [soloA2A, setSoloA2A] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true); setError(null);
    const [a, e] = await Promise.allSettled([api.agents(), api.auditEvents(500)]);
    if (a.status === "fulfilled") setInfo(a.value); else setError(a.reason.message);
    if (e.status === "fulfilled") setEvents(e.value); else setError(e.reason.message);
    setLoading(false);
  };
  useEffect(() => { void load(); }, []);

  const evals = useMemo(() => events.filter((e) => e.action === "audit.evaluate"), [events]);
  const hayA2A = evals.some((e) => e.payload.transporte);
  const rows = useMemo(() => evals.filter((e) => !soloA2A || !hayA2A || e.payload.transporte), [evals, soloA2A, hayA2A]);
  useEffect(() => { if (!selected && rows.length) setSelected(String(rows[0].payload.audit_id)); }, [rows, selected]);

  const auditor = auditorDe(info);
  const modo = info?.copiloto.modo_auditoria ?? health?.audit_mode ?? "—";
  const conteo = info?.auditorias;
  const viaA2A = conteo?.via_a2a ?? 0;
  const total = conteo?.auditorias ?? 0;
  const cadenaOk = Boolean((health?.bases.audit as { cadena_ok?: boolean } | undefined)?.cadena_ok);
  const PAGE = 10;
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const safePage = Math.min(page, pages - 1);

  return <section className="page ag">
    <div className="page-heading">
      <div><span className="eyebrow">A2A 1.0 · REGISTRO NANDA</span><h1>Flujo entre agentes</h1><p>El copiloto de casos no se audita a sí mismo: le pide la auditoría a un agente auditor independiente por protocolo A2A. Aquí se ve quién habló con quién, con qué mensaje y cómo quedó sellado.</p></div>
      <button className="primary" onClick={() => void load()} disabled={loading}>{loading ? "Actualizando…" : "↻ Actualizar"}</button>
    </div>
    {error && <div className="notice error">{error}</div>}
    {info && modo !== "a2a" && <Callout tone="warn" title="El copiloto está auditando en proceso">Las nuevas auditorías no pasan por A2A. Para activar la conversación entre agentes: en .env, NANDA_ENABLED=true y CASES_AUDIT_MODE=a2a, y reiniciar con scripts/start_backend.py.</Callout>}

    <article className="panel ag-arch">
      <div className="panel-title"><div><h2>Arquitectura en vivo</h2><p>Datos del registro NANDA y de la Agent Card que sirve el auditor ahora mismo.</p></div></div>
      <div className="ag-arch-grid">
        <div className="ag-agent copilot">
          <div className="ag-agent-top"><span className="ag-avatar">C</span><div><b>Copiloto de casos</b><small>Agente solicitante · {info?.copiloto.agent_id ?? "—"}</small></div><Tag tone={modo === "a2a" ? "ok" : "warn"}>{modo === "a2a" ? "audita por A2A" : "audita en proceso"}</Tag></div>
          <KV items={[["Módulo", "cases (expedientes y casos)"], ["Identidad A2A", info?.copiloto.agent_id ?? "—"], ["Token", info?.copiloto.token_configurado ? "configurado (Bearer)" : "no configurado"], ["Cliente", "nanda.AuditClient"]]} />
        </div>
        <ol className="ag-wire" aria-label="Pasos del protocolo">
          <li><span>1</span><p>Busca la capacidad <code>{AUDIT_SKILL}</code> en el registro</p></li>
          <li><span>2</span><p>Lee la Agent Card (well-known)</p></li>
          <li><span>3</span><p>SendMessage JSON-RPC + Bearer →</p></li>
          <li><span>4</span><p>← AuditResult (decisión + hallazgos)</p></li>
          <li><span>5</span><p>El auditor sella todo en la cadena de hashes</p></li>
        </ol>
        <AgentCardBox agent={auditor} />
      </div>
    </article>

    <div className="metrics ag-metrics">
      <article className="metric"><span>Auditorías por A2A</span><strong className={viaA2A ? "good" : "warn"}>{viaA2A}</strong><small>Mensajes del copiloto al auditor sellados en la cadena</small></article>
      <article className="metric"><span>Auditorías en proceso</span><strong>{Math.max(0, total - viaA2A)}</strong><small>{Object.entries(conteo?.por_solicitante ?? {}).filter(([k]) => k !== info?.copiloto.agent_id).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"} · llamadas locales, sin mensaje A2A</small></article>
      <article className="metric"><span>Cadena de hashes</span><strong className={cadenaOk ? "good" : "warn"}>{health ? (cadenaOk ? "Íntegra" : "Revisar") : "—"}</strong><small>{conteo?.eventos ?? 0} eventos · verificada por /health</small></article>
      <article className="metric"><span>Modo del copiloto</span><strong>{modo}</strong><small>{auditor?.reachable ? "Auditor A2A en línea" : "Auditor A2A sin respuesta"}</small></article>
    </div>

    <div className="ag-split">
      <article className="panel ag-list">
        <div className="panel-title"><div><h2>Interacciones recientes</h2><p>Últimos {evals.length} eventos de auditoría de la cadena.</p></div>
          {hayA2A && <label className="ag-toggle"><input type="checkbox" checked={soloA2A} onChange={(e) => { setSoloA2A(e.target.checked); setPage(0); }} /> Solo A2A</label>}</div>
        {rows.length ? <>
          <ul className="ag-items">{rows.slice(safePage * PAGE, safePage * PAGE + PAGE).map((e) => {
            const id = String(e.payload.audit_id);
            const exp = expedienteDe(String(e.payload.interaction_id ?? ""));
            return <li key={e.id} className={selected === id ? "active" : ""}>
              <button type="button" onClick={() => setSelected(id)}>
                <span className="ag-item-top"><b>{exp}</b><Tag tone={decisionTone(e.payload.decision)}>{e.payload.decision}</Tag></span>
                <span className="ag-item-sub"><Tag tone={e.payload.transporte ? "ok" : "warn"}>{e.payload.transporte ? "A2A" : "en proceso"}</Tag><span>{e.actor} → auditor · evento #{e.id} · {fmtTs(e.ts)}</span></span>
              </button>
            </li>;
          })}</ul>
          {pages > 1 && <div className="pager"><button type="button" className="secondary small" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>← Anterior</button><span>Página {safePage + 1} de {pages}</span><button type="button" className="secondary small" disabled={safePage >= pages - 1} onClick={() => setPage(safePage + 1)}>Siguiente →</button></div>}
        </> : <div className="empty">{loading ? "Cargando…" : "Aún no hay auditorías en la cadena."}</div>}
      </article>
      <div className="ag-detail">
        {selected ? <>
          <AgentConversation auditId={selected} agents={info} />
          {(() => { const ev = evals.find((e) => String(e.payload.audit_id) === selected); const exp = ev ? expedienteDe(String(ev.payload.interaction_id ?? "")) : null; return exp ? <button type="button" className="text-button" onClick={() => onOpenExpediente(exp)}>Abrir el expediente {exp} →</button> : null; })()}
        </> : <div className="empty">Selecciona una interacción para ver la conversación.</div>}
      </div>
    </div>
  </section>;
}
