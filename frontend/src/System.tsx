import { ReactNode, useEffect, useState } from "react";
import { AgentsInfo, CaseSummary, ComplianceReport, DEFAULT_API_URL, ExpedienteSummary, Health, api, getApiUrl, isCustomApiUrl, normalizeApiUrl, probeApi } from "./api";
import { CountUp, Modal, Skeleton } from "./ui";
import "./system.css";

type ChainCheck = { ok: boolean; eventos: number; auditorias: number; motivo?: string | null; ultimo_hash?: string | null };
const label = (v: string) => v.replaceAll("_", " ");
const sentence = (v: string) => { const s = label(v).toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); };
const host = (url: string) => { if (url.startsWith("/")) return `${window.location.host}${url}`; try { return new URL(url).host; } catch { return url; } };
const sum = (d?: Record<string, number>) => Object.values(d ?? {}).reduce((s, n) => s + n, 0);

// ------------------------------------------------------------------ Conexión
export function ConnectionDialog({ onClose, onConnected }: { onClose: () => void; onConnected: (url: string | null) => void }) {
  const [value, setValue] = useState(isCustomApiUrl() ? getApiUrl() : "");
  const [state, setState] = useState<{ kind: "idle" | "testing" | "ok" | "error"; text?: string }>({ kind: "idle" });
  const test = async (save: boolean) => {
    const candidate = value.trim() || DEFAULT_API_URL;
    setState({ kind: "testing" });
    try {
      const { health, ms } = await probeApi(candidate);
      setState({ kind: "ok", text: `Conectado a ${host(normalizeApiUrl(candidate))} · ${health.status} · API v${health.version} · ${ms} ms` });
      if (save) onConnected(value.trim() || null);
    } catch (error) { setState({ kind: "error", text: (error as Error).message }); }
  };
  return <Modal title="Conexión con el backend" subtitle={<>Ahora: <code>{getApiUrl()}</code>{isCustomApiUrl() ? " (fijada en este navegador)" : " (la del despliegue)"}</>} onClose={onClose}
    footer={<>
      {isCustomApiUrl() && <button type="button" className="secondary" onClick={() => onConnected(null)}>Usar la del despliegue</button>}
      <button type="button" className="secondary" disabled={state.kind === "testing"} onClick={() => void test(false)}>Probar</button>
      <button type="button" className="primary" disabled={state.kind === "testing"} onClick={() => void test(true)}>{state.kind === "testing" ? "Probando…" : "Probar y conectar"}</button>
    </>}>
    <label className="modal-field">URL del backend
      <input value={value} onChange={(e) => { setValue(e.target.value); setState({ kind: "idle" }); }} onKeyDown={(e) => { if (e.key === "Enter") void test(true); }} placeholder="https://xxxx.trycloudflare.com" inputMode="url" spellCheck={false} />
    </label>
    <p className="modal-help">Pega la URL que imprime <code>python scripts/start_backend.py</code> («URL Cloudflare (API)»). El túnel rápido de Cloudflare cambia en cada arranque: si el panel deja de responder, vuelve a pegarla aquí. También sirve abrir el front con <code>?api=&lt;url&gt;</code>.</p>
    {state.kind === "ok" && <div className="conn-result ok">✓ {state.text}</div>}
    {state.kind === "error" && <div className="conn-result bad">! {state.text}</div>}
  </Modal>;
}

// ---------------------------------------------------------- Estado del sistema
function Service({ name, detail, ok, value, warn }: { name: string; detail: ReactNode; ok: boolean | null; value: string; warn?: boolean }) {
  const tone = ok == null ? "idle" : ok ? (warn ? "warn" : "ok") : "bad";
  return <article className={`sys-service ${tone}`}>
    <div className="sys-service-top"><span className={`status-dot ${tone}`} /><b>{name}</b><span className={`sys-state ${tone}`}>{value}</span></div>
    <small>{detail}</small>
  </article>;
}

function Bars({ data }: { data: Record<string, number> }) {
  const total = Object.values(data).reduce((s, n) => s + n, 0) || 1;
  return <div className="sys-bars">{Object.entries(data).sort((a, b) => b[1] - a[1]).map(([k, n]) => <div key={k} className="sys-bar-row">
    <span>{sentence(k)}</span><b><CountUp value={n} /></b><div className="sys-bar"><i className={k.toLowerCase()} style={{ width: `${Math.max(2, (n / total) * 100)}%` }} /></div>
  </div>)}</div>;
}

function Store({ title, icon, children }: { title: string; icon: string; children: ReactNode }) {
  return <article className="panel sys-store"><div className="sys-store-head"><span>{icon}</span><h2>{title}</h2></div>{children}</article>;
}

function Stat({ value, label: l }: { value?: number | null; label: string }) {
  return <div className="sys-stat"><strong>{value == null ? "—" : <CountUp value={value} />}</strong><span>{l}</span></div>;
}

export function SystemPage({ health, healthMs, checkedAt, cases, expedientes, loading, onRefresh, onOpenCase, onConnection }: {
  health: Health | null; healthMs: number | null; checkedAt: Date | null; cases: CaseSummary[]; expedientes: ExpedienteSummary[]; loading: boolean;
  onRefresh: () => void; onOpenCase: (id: string) => void; onConnection: () => void;
}) {
  const [agents, setAgents] = useState<AgentsInfo | null>(null);
  const [chain, setChain] = useState<ChainCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [chainError, setChainError] = useState<string | null>(null);
  useEffect(() => { void api.agents().then(setAgents).catch(() => setAgents(null)); }, [checkedAt]);

  const verify = async () => {
    setChecking(true); setChainError(null);
    try { setChain(await api.verifyChain()); } catch (e) { setChainError((e as Error).message); } finally { setChecking(false); }
  };

  const b = health?.bases;
  const audit = b?.audit;
  const auditor = agents?.registro.agentes.find((a) => a.capabilities.includes("audit_candidate_response"));
  const comp = (b?.compliance ?? {}) as Record<string, unknown>;
  const modelos = Object.entries(health?.ollama.models ?? {});
  const rag = b?.rag;
  const indicesAlineados = rag ? rag.versiones_sql === rag.vectores && rag.vectores === rag.bm25 : false;

  return <section className="page sys">
    <div className="page-heading">
      <div><span className="eyebrow">MONITOR DE LA PLATAFORMA</span><h1>Estado del sistema</h1><p>Servicios, bases de datos y cadena de auditoría del backend al que está conectado este panel. Se verifica en vivo con <code>/health</code>.</p></div>
      <div className="page-actions"><button className="secondary" onClick={onConnection}>⇆ Conexión</button><button className="primary" onClick={onRefresh} disabled={loading}>{loading ? "Verificando…" : "↻ Verificar ahora"}</button></div>
    </div>

    <article className={`sys-banner ${health ? (health.status === "ok" ? "ok" : "warn") : "bad"}`}>
      <span className={`status-dot big ${health ? (health.status === "ok" ? "ok" : "warn") : "bad"}`} />
      <div><b>{health ? (health.status === "ok" ? "Todos los servicios operativos" : "Servicio degradado") : "Sin conexión con el backend"}</b>
        <small>{host(getApiUrl())} · {health ? `API v${health.version}` : "no responde"}{healthMs != null && health ? ` · ${healthMs} ms` : ""}{checkedAt ? ` · verificado ${checkedAt.toLocaleTimeString("es-PE")}` : ""}</small></div>
      {!health && <button className="primary" onClick={onConnection}>Configurar conexión</button>}
    </article>

    <div className="sys-services stagger">
      {health ? <>
        <Service name="API backend" ok value={`v${health.version}`} detail={<>FastAPI unificada · {host(getApiUrl())}</>} />
        <Service name="Ollama" ok={health.ollama.reachable} value={health.ollama.reachable ? "en línea" : "caído"} detail={health.ollama.error ?? health.ollama.host ?? "LLM local"} />
        {modelos.map(([m, okModel]) => <Service key={m} name={m === health.modelos?.embeddings ? "Embeddings" : "Modelo LLM"} ok={okModel} value={okModel ? "cargado" : "falta"} detail={<code>{m}</code>} />)}
        <Service name="Agente auditor A2A" ok={auditor ? auditor.reachable : null} warn={health.audit_mode !== "a2a"} value={auditor?.reachable ? (health.audit_mode === "a2a" ? "conversando" : "en línea") : agents ? "sin respuesta" : "—"} detail={<>Modo del copiloto: <b>{health.audit_mode}</b> · política {health.policy_version}</>} />
        <Service name="Cadena de auditoría" ok={audit?.cadena_ok ?? null} value={audit?.cadena_ok ? "íntegra" : "revisar"} detail={audit?.cadena_motivo ?? `${audit?.eventos ?? 0} eventos encadenados (SHA-256)`} />
      </> : loading ? Array.from({ length: 6 }, (_, i) => <article className="sys-service" key={i}><Skeleton h={14} w="70%" /><Skeleton h={11} w="50%" /></article>) : null}
    </div>

    <div className="sys-stores stagger">
      <Store title="Normativa (RAG)" icon="⌘">
        <div className="sys-stats"><Stat value={rag?.versiones_sql} label="versiones" /><Stat value={rag?.vectores} label="vectores" /><Stat value={rag?.bm25} label="BM25" /></div>
        <small className={`sys-note ${indicesAlineados ? "ok" : "warn"}`}>{rag ? (indicesAlineados ? "✓ Los tres índices están alineados" : "! Los índices no coinciden: reingesta recomendada") : "—"}</small>
      </Store>
      <Store title="Auditoría" icon="⛨">
        <div className="sys-stats"><Stat value={audit?.auditorias} label="auditorías" /><Stat value={audit?.via_a2a} label="vía A2A" /><Stat value={audit?.revisiones} label="revisiones" /></div>
        {audit?.por_decision && <Bars data={audit.por_decision} />}
      </Store>
      <Store title="Compliance" icon="✎">
        {Object.entries(comp).filter(([, v]) => v && typeof v === "object").map(([k, v]) => <div key={k} className="sys-comp"><span>{label(k)}</span><div className="chips">{Object.entries(v as Record<string, number>).map(([estado, n]) => <span key={estado} className={`tag ${estado === "validada" ? "ok" : estado === "propuesta" ? "warn" : "neutral"}`}>{n} {label(estado)}</span>)}</div></div>)}
        {!Object.keys(comp).length && <small className="muted">Sin datos de compliance.</small>}
      </Store>
      <Store title="Casos y expedientes" icon="✓">
        <div className="sys-stats"><Stat value={b?.cases ? sum(b.cases.casos) : null} label="casos" /><Stat value={b?.cases ? sum(b.cases.expedientes) : null} label="expedientes" /></div>
        {b?.cases?.expedientes && <Bars data={b.cases.expedientes} />}
      </Store>
    </div>

    <div className="two-col">
      <article className="panel">
        <div className="panel-title"><div><h2>Verificación de la cadena de auditoría</h2><p>Recalcula cada hash (SHA-256 sobre el anterior) y lo cruza con las tablas de datos.</p></div><button className="secondary small" onClick={() => void verify()} disabled={checking || !health}>{checking ? "Recalculando…" : "Verificar cadena completa"}</button></div>
        {chainError && <div className="conn-result bad">! {chainError}</div>}
        {chain ? <div className={`sys-chain ${chain.ok ? "ok" : "bad"}`}>
          <b>{chain.ok ? "✓ Cadena íntegra" : "✕ Cadena alterada"}</b>
          <span>{chain.eventos.toLocaleString("es-PE")} eventos · {chain.auditorias.toLocaleString("es-PE")} auditorías</span>
          {chain.ultimo_hash && <code title={chain.ultimo_hash}>último hash {chain.ultimo_hash.slice(0, 16)}…{chain.ultimo_hash.slice(-6)}</code>}
          {chain.motivo && <span>{chain.motivo}</span>}
        </div> : <p className="muted">Pulsa «Verificar cadena completa» para recalcularla ahora.</p>}
      </article>
      <article className="panel">
        <div className="panel-title"><div><h2>Actividad reciente</h2><p>Últimos casos individuales evaluados · {expedientes.length} expedientes importados.</p></div></div>
        {cases.length ? <ul className="sys-activity stagger">{cases.slice(0, 6).map((c) => <li key={c.case_id}><button type="button" onClick={() => onOpenCase(c.case_id)}><code>{c.case_id}</code><span>{label(c.tipo_evento)}</span><span className={`tag ${c.decision === "ALLOW" ? "ok" : c.decision === "WARN" ? "warn" : "bad"}`}>{c.decision ?? "—"}</span><small>{new Date(c.evaluado_en).toLocaleDateString("es-PE")}</small></button></li>)}</ul>
          : <div className="empty">Aún no hay casos individuales evaluados.</div>}
      </article>
    </div>
  </section>;
}

// ------------------------------------------------------ Reporte de cumplimiento
export function ReportPage() {
  const [report, setReport] = useState<ComplianceReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true); setError(null);
    try { setReport((await api.complianceReport()).reporte); } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  const porEstado = (report?.items ?? []).reduce<Record<string, number>>((m, i) => ({ ...m, [i.estado]: (m[i.estado] ?? 0) + 1 }), {});
  const pendientes = Object.entries(report?.propuestas_pendientes ?? {});
  return <section className="page rep">
    <div className="page-heading"><div><span className="eyebrow">MONITOREO DE OBLIGACIONES</span><h1>Reporte de cumplimiento</h1><p>Obligaciones LA/FT <b>validadas</b> con su estado de plazo y la exposición potencial asociada. Las propuestas sin validar no entran al reporte.</p></div><button className="primary" onClick={() => void load()} disabled={loading}>{loading ? "Generando…" : "↻ Regenerar"}</button></div>
    {error && <div className="notice error">! {error}</div>}
    {loading && !report ? <div className="metrics">{Array.from({ length: 4 }, (_, i) => <article className="metric" key={i}><Skeleton h={12} w="50%" /><Skeleton h={28} w="40%" /><Skeleton h={11} w="70%" /></article>)}</div> : report && <>
      <div className="metrics stagger">
        <article className="metric"><span>Fecha de corte</span><strong>{report.fecha_corte.split("-").reverse().join("/")}</strong><small>Plazos calculados a esta fecha</small></article>
        <article className="metric"><span>Obligaciones en el reporte</span><strong><CountUp value={report.items.length} /></strong><small>{Object.entries(porEstado).map(([k, n]) => `${n} ${label(k)}`).join(" · ") || "Ninguna validada todavía"}</small></article>
        <article className="metric"><span>Propuestas por validar</span><strong className="warn"><CountUp value={pendientes.reduce((s, [, n]) => s + n, 0)} /></strong><small>{pendientes.map(([k, n]) => `${n} ${label(k)}`).join(" · ") || "—"}</small></article>
        <article className="metric"><span>Advertencias</span><strong className={report.advertencias.length ? "warn" : "good"}><CountUp value={report.advertencias.length} /></strong><small>{report.rotulo}</small></article>
      </div>
      {report.advertencias.length > 0 && <article className="panel rep-warnings"><h2>Advertencias del reporte</h2><ul>{report.advertencias.map((a) => <li key={a}>{a}</li>)}</ul></article>}
      {report.items.length ? <div className="rep-items stagger">{report.items.map((i) => <article key={i.obligacion.codigo} className={`panel rep-item ${i.estado}`}>
        <div className="rep-item-top"><code>{i.obligacion.codigo}</code><span className={`tag ${i.estado === "atrasado" ? "bad" : i.estado === "por_vencer" ? "warn" : "ok"}`}>{label(i.estado)}{i.dias_atraso > 0 ? ` · +${i.dias_atraso} días` : ""}</span></div>
        <h3>{i.obligacion.accion_requerida}</h3>
        <small>{i.obligacion.norma_codigo}, art. {i.obligacion.articulo_numero} · versión {i.obligacion.version_id} · {i.obligacion.sujeto}</small>
        <div className="rep-exp">{i.rango_uit[0] == null && i.rango_uit[1] == null ? "Monto no determinado" : `Exposición potencial: ${i.rango_uit[0] ?? "?"}–${i.rango_uit[1] ?? "?"} UIT`}</div>
      </article>)}</div>
        : <div className="empty rep-empty"><div><b>Aún no hay obligaciones validadas</b><p>El reporte solo considera obligaciones que el equipo validó. Hay {pendientes.reduce((s, [, n]) => s + n, 0)} propuestas extraídas de la normativa esperando revisión humana (<code>python -m modules.compliance.cli proposals</code>).</p></div></div>}
    </>}
  </section>;
}
