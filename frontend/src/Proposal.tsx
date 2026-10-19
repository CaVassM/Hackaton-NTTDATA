import { useEffect, useMemo, useState } from "react";
import { api, AuditRecord, ComplianceReport, ExpedienteDetalle, Health, ReportItem } from "./api";

/* Centro de alertas inteligentes y vigilancia de plazos — datos REALES del backend:
   expedientes evaluados (/cases/expedientes?detalle=true), reporte de compliance
   (solo obligaciones validadas), propuestas pendientes y la cadena de auditoría
   (las revisiones humanas se registran con POST /audit/{id}/review). */

type Tipo = "AMBAS" | "NORMATIVA" | "PLAZO_INTERNO";
type Alerta = { id: string; tipo: Tipo; fila: Record<string, string>; dias: number; auditId: string };
type Tab = "todas" | "normativa" | "plazo" | "ambas" | "obligaciones";
type Revision = { decision: string; reviewer: string; at: string };

const TIPO_LABEL: Record<Tipo, string> = { AMBAS: "Normativa y plazo interno", NORMATIVA: "Incumplimiento normativo", PLAZO_INTERNO: "Vencimiento de plazo interno" };
const RESULTADO_LABEL: Record<string, string> = { POSIBLE_INCUMPLIMIENTO: "Posible incumplimiento", INFORMACION_INSUFICIENTE: "Información insuficiente", SIN_INCUMPLIMIENTO_DETECTADO: "Sin indicios detectados" };
const PRIORIDAD_ORDEN: Record<string, number> = { ALTA: 0, MEDIA: 1, BAJA: 2 };
const PAGE = 12;
const REVIEWER_KEY = "centro-alertas-revisor";

const tone = (t: Tipo) => (t === "PLAZO_INTERNO" ? "amber" : "red");
const num = (v?: string) => (v && !Number.isNaN(Number(v)) ? Number(v) : 0);
const fmtFecha = (iso?: string | null) => (iso ? iso.split("-").reverse().join("/") : "—");
const soles = (v?: number | null) => (v == null ? "—" : new Intl.NumberFormat("es-PE", { style: "currency", currency: "PEN", maximumFractionDigits: 0 }).format(v));
const diasEntre = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
const sinCita = (fila: Record<string, string>) => (fila.fuente_legal ?? "").includes("NO_DISPONIBLE");

function leerRevisor(): string {
  try { return localStorage.getItem(REVIEWER_KEY) ?? ""; } catch { return ""; }
}

function descargarCsv(nombre: string, filas: string[][]) {
  const texto = filas.map((f) => f.map((v) => `"${String(v ?? "").replaceAll('"', '""')}"`).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([`﻿${texto}`], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = nombre; a.click();
  URL.revokeObjectURL(url);
}

export default function ProposalPage({ health, onOpenExpediente }: { health: Health | null; onOpenExpediente: (id: string) => void }) {
  const [expedientes, setExpedientes] = useState<ExpedienteDetalle[]>([]);
  const [reporte, setReporte] = useState<ComplianceReport | null>(null);
  const [pendientes, setPendientes] = useState<number | null>(null);
  const [errores, setErrores] = useState<string[]>([]);
  const [cargando, setCargando] = useState(true);
  const [tab, setTab] = useState<Tab>("todas");
  const [buscar, setBuscar] = useState("");
  const [modalidad, setModalidad] = useState("");
  const [prioridad, setPrioridad] = useState("");
  const [estadoRevision, setEstadoRevision] = useState("");
  const [pagina, setPagina] = useState(0);
  const [revisor, setRevisor] = useState(leerRevisor);
  const [revisiones, setRevisiones] = useState<Record<string, Revision>>({});
  const [enviando, setEnviando] = useState<string | null>(null);
  const [aviso, setAviso] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const cargar = async () => {
    setCargando(true); setErrores([]);
    const [exp, rep, prop] = await Promise.allSettled([api.expedientesDetalle(), api.complianceReport(), api.pendingProposals()]);
    const errs: string[] = [];
    if (exp.status === "fulfilled") setExpedientes(exp.value); else errs.push(`Expedientes: ${exp.reason.message}`);
    if (rep.status === "fulfilled") setReporte(rep.value.reporte); else errs.push(`Reporte de compliance: ${rep.reason.message}`);
    if (prop.status === "fulfilled") setPendientes(Object.values(prop.value).reduce((n, lista) => n + lista.length, 0));
    else errs.push(`Propuestas: ${prop.reason.message}`);
    setErrores(errs); setCargando(false);
  };
  useEffect(() => { void cargar(); }, []);
  useEffect(() => { try { localStorage.setItem(REVIEWER_KEY, revisor); } catch { /* sin almacenamiento */ } }, [revisor]);

  const alertas: Alerta[] = useMemo(() => expedientes
    .filter((e) => ["AMBAS", "NORMATIVA", "PLAZO_INTERNO"].includes(e.fila.tipo_alerta_esperada))
    .map((e) => ({ id: e.id_caso, tipo: e.fila.tipo_alerta_esperada as Tipo, fila: e.fila, dias: num(e.fila.dias_de_retraso_interno), auditId: e.fila.audit_id ?? "" }))
    .sort((a, b) => (PRIORIDAD_ORDEN[a.fila.prioridad] ?? 9) - (PRIORIDAD_ORDEN[b.fila.prioridad] ?? 9)
      || Number(b.tipo === "AMBAS") - Number(a.tipo === "AMBAS") || b.dias - a.dias || a.id.localeCompare(b.id)), [expedientes]);

  const obligaciones: ReportItem[] = useMemo(() => (reporte?.items ?? []).filter((i) => i.estado === "atrasado" || i.estado === "por_vencer"), [reporte]);

  // Revisiones ya registradas en la cadena para las alertas destacadas (no se piden las 160).
  const destacadasIds = alertas.slice(0, 4).map((a) => a.auditId).filter(Boolean).join(",");
  useEffect(() => {
    const ids = destacadasIds ? destacadasIds.split(",") : [];
    ids.forEach((id) => {
      void api.auditRecord(id).then((rec: AuditRecord) => {
        const ult = rec.reviews[rec.reviews.length - 1];
        if (ult) setRevisiones((prev) => ({ ...prev, [id]: { decision: ult.decision, reviewer: ult.reviewer, at: ult.created_at } }));
      }).catch(() => { /* sin persistencia o sin auditoría: queda pendiente */ });
    });
  }, [destacadasIds]);

  const modalidades = useMemo(() => [...new Set(alertas.map((a) => a.fila.modalidad_analisis).filter(Boolean))].sort(), [alertas]);
  const revisionDe = (a: Alerta) => revisiones[a.auditId]?.decision ?? "pendiente";

  const filtradas = useMemo(() => {
    const q = buscar.trim().toLowerCase();
    return alertas.filter((a) => (tab === "todas" || (tab === "normativa" && a.tipo !== "PLAZO_INTERNO") || (tab === "plazo" && a.tipo !== "NORMATIVA") || (tab === "ambas" && a.tipo === "AMBAS"))
      && (!modalidad || a.fila.modalidad_analisis === modalidad)
      && (!prioridad || a.fila.prioridad === prioridad)
      && (!estadoRevision || revisionDe(a) === estadoRevision)
      && (!q || a.id.toLowerCase().includes(q) || (a.fila.hechos_relevantes_del_caso ?? "").toLowerCase().includes(q) || (a.fila.norma_a_consultar ?? "").toLowerCase().includes(q)));
  }, [alertas, tab, modalidad, prioridad, estadoRevision, buscar, revisiones]);

  const nNormativa = alertas.filter((a) => a.tipo !== "PLAZO_INTERNO").length;
  const conPlazo = alertas.filter((a) => a.tipo !== "NORMATIVA");
  const nPlazo = conPlazo.length + obligaciones.filter((o) => o.estado === "atrasado").length;
  const atrasos = [...conPlazo.map((a) => a.dias), ...obligaciones.map((o) => o.dias_atraso)].filter((d) => d > 0);
  const promAtraso = atrasos.length ? (atrasos.reduce((s, d) => s + d, 0) / atrasos.length).toFixed(1) : null;
  const total = alertas.length + obligaciones.length;
  const evaluados = expedientes.length;
  const noPublicables = expedientes.filter((e) => ["BLOCK", "ESCALATE"].includes(e.fila.decision_auditoria)).length;
  const decisiones = expedientes.reduce<Record<string, number>>((m, e) => ({ ...m, [e.fila.decision_auditoria || "SIN_AUDITORIA"]: (m[e.fila.decision_auditoria || "SIN_AUDITORIA"] ?? 0) + 1 }), {});

  const enObligaciones = tab === "obligaciones";
  const destacadas = enObligaciones ? [] : filtradas.slice(0, 2);
  const cola = enObligaciones ? [] : filtradas.slice(2);
  const paginas = Math.max(1, Math.ceil(cola.length / PAGE));
  const pag = Math.min(pagina, paginas - 1);

  const revisar = async (a: Alerta, aprobar: boolean) => {
    if (!revisor.trim()) { setAviso({ kind: "error", text: "Escribe tu nombre en “Revisor”: la revisión humana queda firmada en la cadena de auditoría." }); return; }
    if (!a.auditId) { setAviso({ kind: "error", text: `${a.id} no tiene auditoría registrada; no se puede revisar.` }); return; }
    const comentario = window.prompt(aprobar ? `Confirmar la alerta ${a.id}. Comentario (opcional):` : `Descartar ${a.id} como falso positivo. Motivo:`, "");
    if (comentario === null) return;
    setEnviando(a.auditId);
    try {
      const r = await api.reviewAudit(a.auditId, { reviewer: revisor.trim(), aprobar, comentario: comentario || null });
      setRevisiones((prev) => ({ ...prev, [a.auditId]: { decision: r.decision, reviewer: r.reviewer, at: r.created_at } }));
      setAviso({ kind: "ok", text: `${a.id}: revisión “${r.decision}” registrada por ${r.reviewer} en la cadena de auditoría.` });
    } catch (e) { setAviso({ kind: "error", text: `No se pudo registrar la revisión de ${a.id}: ${(e as Error).message}` }); }
    finally { setEnviando(null); }
  };

  const exportar = () => {
    const filas = [["id_caso", "tipo_alerta", "resultado", "modalidad", "norma_a_consultar", "prioridad", "fecha_limite_interna", "fecha_atencion", "dias_de_retraso_interno", "decision_auditoria", "fuente_legal", "revision_humana"]];
    filtradas.forEach((a) => filas.push([a.id, a.tipo, a.fila.resultado_esperado, a.fila.modalidad_analisis, a.fila.norma_a_consultar, a.fila.prioridad, a.fila.fecha_limite_interna, a.fila.fecha_atencion, a.fila.dias_de_retraso_interno, a.fila.decision_auditoria, a.fila.fuente_legal, revisionDe(a)]));
    obligaciones.forEach((o) => filas.push([o.obligacion.codigo, "OBLIGACION_COMPLIANCE", o.estado, "", `${o.obligacion.norma_codigo} art. ${o.obligacion.articulo_numero}`, "", "", "", String(o.dias_atraso), "", `version ${o.obligacion.version_id}`, ""]));
    descargarCsv("centro_de_alertas.csv", filas);
  };

  const TABS: Array<[Tab, string, number, string]> = [
    ["todas", "Todas las alertas", alertas.length, ""],
    ["normativa", "Incumplimiento normativo", nNormativa, "red"],
    ["plazo", "Vencimiento de plazos", conPlazo.length, "amber"],
    ["ambas", "Ambas", alertas.filter((a) => a.tipo === "AMBAS").length, "red"],
    ["obligaciones", "Obligaciones (compliance)", obligaciones.length, "blue"],
  ];

  return <section className="page pr">
    <div className="pr-hero">
      <div>
        <div className="pr-eyebrow"><span className="pr-badge red">SUPERVISIÓN ACTIVA</span><span className="pr-eyebrow-text">• Motor RAG local · política {health?.policy_version ?? "—"} · auditoría {health?.audit_mode ?? "—"}</span></div>
        <h1>Centro de Alertas Inteligentes y Vigilancia de Plazos</h1>
        <p>Alertas de los expedientes evaluados por el agente (indicios normativos y atrasos internos) y obligaciones LA/FT validadas con plazo vencido o por vencer. Cada alerta es una hipótesis para revisión humana.</p>
      </div>
      <div className="pr-hero-actions">
        <button className="pr-btn light" type="button" onClick={() => void cargar()} disabled={cargando}>{cargando ? "Cargando…" : "↻ Actualizar"}</button>
        <button className="pr-btn dark" type="button" onClick={exportar} disabled={!filtradas.length && !obligaciones.length}>⬇ Exportar alertas (CSV)</button>
      </div>
    </div>

    {errores.map((e) => <div className="notice error pr-inline-notice" key={e}>! {e}</div>)}
    {aviso && <div className={`notice ${aviso.kind === "ok" ? "success" : "error"} pr-inline-notice`} role="status">{aviso.kind === "ok" ? "✓" : "!"} {aviso.text}<button aria-label="Cerrar" onClick={() => setAviso(null)}>×</button></div>}

    <div className="pr-kpis">
      <article className="pr-kpi"><header><span>Total alertas activas</span><i className="red">●</i></header>
        <div className="pr-kpi-main"><strong>{total}</strong></div><small>{evaluados} expedientes evaluados · {obligaciones.length} obligaciones</small>
        {evaluados > 0 && <div className="pr-kpi-bar"><span style={{ width: `${Math.round((alertas.length / evaluados) * 100)}%` }} /></div>}</article>
      <article className="pr-kpi"><header><span>Incumplimiento normativo</span><i>⚖</i></header>
        <div className="pr-kpi-main"><strong>{nNormativa}</strong><span className="pr-tag red">Posible incumplimiento</span></div>
        <small>{alertas.length ? `${Math.round((nNormativa / alertas.length) * 100)}% de las alertas` : "Sin alertas"}</small></article>
      <article className="pr-kpi"><header><span>Vencimiento de plazos</span><i>⏰</i></header>
        <div className="pr-kpi-main"><strong>{nPlazo}</strong><span className="pr-tag amber">Excedidos</span></div>
        <small>{promAtraso ? `Promedio: +${promAtraso} días calendario` : "Sin atrasos calculables"}</small></article>
      <article className="pr-kpi"><header><span>No publicables (auditoría)</span><i>⛨</i></header>
        <div className="pr-kpi-main"><strong>{noPublicables}</strong></div>
        <small>{Object.entries(decisiones).map(([d, n]) => `${d} ${n}`).join(" · ") || "Sin auditorías"}</small></article>
      <article className="pr-kpi"><header><span>Propuestas por validar</span><i>✎</i></header>
        <div className="pr-kpi-main"><strong>{pendientes ?? "—"}</strong></div>
        <small>Obligaciones, infracciones y enlaces de compliance pendientes de revisión humana</small></article>
    </div>

    <div className="pr-filters">
      <div className="pr-tabs">
        {TABS.map(([id, label, n, t]) => <button key={id} type="button" className={`${tab === id ? "active" : ""} ${t}`} onClick={() => { setTab(id); setPagina(0); }}>{t && <span className={`pr-dot ${t}`} />}{label}<b>{n}</b></button>)}
      </div>
      <div className="pr-fields">
        <input value={buscar} onChange={(e) => { setBuscar(e.target.value); setPagina(0); }} placeholder="🔍 Buscar por caso (SYN-0003), hechos o norma…" aria-label="Buscar" />
        <select value={modalidad} onChange={(e) => { setModalidad(e.target.value); setPagina(0); }} aria-label="Modalidad"><option value="">Modalidad: todas</option>{modalidades.map((m) => <option key={m}>{m}</option>)}</select>
        <select value={prioridad} onChange={(e) => { setPrioridad(e.target.value); setPagina(0); }} aria-label="Prioridad"><option value="">Prioridad: todas</option><option>ALTA</option><option>MEDIA</option><option>BAJA</option></select>
        <select value={estadoRevision} onChange={(e) => { setEstadoRevision(e.target.value); setPagina(0); }} aria-label="Revisión"><option value="">Revisión: todas</option><option value="pendiente">Pendiente</option><option value="aprobada">Confirmada</option><option value="rechazada">Descartada</option></select>
        <input className="pr-reviewer" value={revisor} onChange={(e) => setRevisor(e.target.value)} placeholder="Revisor (tu nombre)" aria-label="Revisor" />
      </div>
    </div>

    {!cargando && !total && <div className="empty">No hay alertas. Importa expedientes en “Gestión de casos” o valida obligaciones de compliance para ver plazos.</div>}

    {destacadas.map((a) => <AlertaCard key={a.id} a={a} revision={revisiones[a.auditId]} enviando={enviando === a.auditId}
      onAbrir={() => onOpenExpediente(a.id)} onRevisar={(ok) => void revisar(a, ok)} />)}

    {enObligaciones && (obligaciones.length ? <div className="pr-pair">{obligaciones.map((o) => <ObligacionCard key={o.obligacion.codigo} o={o} />)}</div>
      : <div className="empty">No hay obligaciones validadas con plazo vencido o por vencer. El reporte solo usa obligaciones VALIDADAS en compliance.</div>)}

    {!enObligaciones && obligaciones.length > 0 && tab === "todas" && <div className="pr-pair">{obligaciones.slice(0, 2).map((o) => <ObligacionCard key={o.obligacion.codigo} o={o} />)}</div>}

    {cola.length > 0 && <article className="pr-queue">
      <div className="pr-queue-head"><div><h2>Cola de vigilancia continua</h2><p>Resto de alertas filtradas, ordenadas por prioridad, tipo y días de atraso.</p></div><b>Mostrando {Math.min(PAGE, cola.length - pag * PAGE)} de {cola.length}</b></div>
      <div className="pr-table-wrap"><table>
        <thead><tr><th>Caso</th><th>Tipología</th><th>Normativa / plazo</th><th>Prioridad</th><th>Atraso interno</th><th>Auditoría</th><th>Revisión</th><th>Acción</th></tr></thead>
        <tbody>{cola.slice(pag * PAGE, (pag + 1) * PAGE).map((a) => <tr key={a.id}>
          <td><code>{a.id}</code></td>
          <td><span className={`pr-dot ${tone(a.tipo)}`} /> {TIPO_LABEL[a.tipo]}</td>
          <td className="pr-muted">{a.fila.norma_a_consultar}{a.dias > 0 ? ` · +${a.dias} días` : ""}</td>
          <td><b>{a.fila.prioridad}</b></td>
          <td className="pr-mono-blue">{a.fila.dias_de_retraso_interno ? `${a.fila.dias_de_retraso_interno} días` : "No determinable"}</td>
          <td><span className={`pr-state ${a.fila.decision_auditoria === "WARN" ? "amber" : "red"}`}>{a.fila.decision_auditoria || "—"}</span></td>
          <td>{revisionDe(a)}</td>
          <td><button type="button" className="pr-link" onClick={() => onOpenExpediente(a.id)}>Ver expediente</button></td>
        </tr>)}</tbody>
      </table></div>
      {paginas > 1 && <div className="pager"><button type="button" className="secondary small" disabled={pag === 0} onClick={() => setPagina(pag - 1)}>← Anterior</button><span>Página {pag + 1} de {paginas}</span><button type="button" className="secondary small" disabled={pag >= paginas - 1} onClick={() => setPagina(pag + 1)}>Siguiente →</button></div>}
    </article>}

    <p className="pr-note">Datos reales del backend. Las alertas son hipótesis de contraste para revisión humana: no determinan responsabilidad penal ni sanción. Los montos son <b>exposición potencial, no sanción determinada</b>.{reporte?.advertencias?.length ? ` ${reporte.advertencias.join(" ")}` : ""}</p>
  </section>;
}

function AlertaCard({ a, revision, enviando, onAbrir, onRevisar }: { a: Alerta; revision?: Revision; enviando: boolean; onAbrir: () => void; onRevisar: (aprobar: boolean) => void }) {
  const f = a.fila;
  const t = tone(a.tipo);
  const conFechas = f.fecha_registro && f.fecha_limite_interna && f.fecha_atencion;
  const totalDias = conFechas ? Math.max(1, diasEntre(f.fecha_registro, f.fecha_atencion)) : 0;
  const plazoDias = conFechas ? Math.max(0, diasEntre(f.fecha_registro, f.fecha_limite_interna)) : 0;
  const okPct = conFechas ? Math.min(100, Math.round((plazoDias / totalDias) * 100)) : 0;
  return <article className={`pr-card ${t}`}>
    <div className="pr-card-head">
      <span className={`pr-badge ${t}-soft`}>● {TIPO_LABEL[a.tipo]}</span><code>{a.id}</code><span className="pr-sep">•</span><h2>{RESULTADO_LABEL[f.resultado_esperado] ?? f.resultado_esperado} · {f.modalidad_analisis}</h2>
    </div>
    <div className="pr-card-head sub">
      <span className="pr-outline red">PRIORIDAD {f.prioridad}</span>
      <span className="pr-outline blue mono">Auditoría: {f.decision_auditoria || "—"}</span>
      {a.dias > 0 && <span className="pr-badge red-soft mono">+{a.dias} días de atraso interno</span>}
      {revision && <span className={`pr-state ${revision.decision === "aprobada" ? "red" : "amber"}`}>Revisión: {revision.decision} · {revision.reviewer}</span>}
    </div>
    <div className="pr-info">
      <div><label>Normativa a consultar</label><strong>▤ {f.norma_a_consultar}</strong><small>{sinCita(f) ? "Texto del DL 1106 no cargado en el corpus: sin cita verificable" : f.fuente_legal}</small></div>
      <div><label>Plazo interno</label><strong>◔ {conFechas ? `${fmtFecha(f.fecha_limite_interna)} (límite)` : "No determinable"}</strong><small>{f.explicacion_plazo}</small></div>
      <div><label>Reglas y señales</label><strong>{f.reglas_version || "—"}</strong><small>{(f.senales_detectadas || "sin señales").replaceAll("|", " · ")}</small></div>
    </div>
    <div className="pr-finding">
      <div className="pr-finding-head"><b>▥ Fundamento de la alerta</b>{f.version_id_citada && <code>version_id {f.version_id_citada}</code>}</div>
      <p>{f.por_que_si_o_no}</p>
      <div className="pr-compare">
        <div><header><b>▤ Hechos del expediente</b></header><blockquote>{(f.hechos_relevantes_del_caso ?? "").slice(0, 420)}{(f.hechos_relevantes_del_caso ?? "").length > 420 ? "…" : ""}</blockquote></div>
        <div><header><b>◈ Hipótesis de contraste</b></header><blockquote>{f.razon_de_aplicacion_normativa}</blockquote></div>
      </div>
    </div>
    {conFechas && <div className="pr-timeline">
      <div className="pr-timeline-top"><span>Línea temporal del plazo interno</span><b className={a.dias > 0 ? "red-text" : ""}>{totalDias} de {plazoDias} días consumidos{a.dias > 0 ? ` (+${a.dias})` : ""}</b></div>
      <div className="pr-track"><span className="ok" style={{ width: `${okPct}%` }} />{a.dias > 0 && <span className="over" style={{ width: `${100 - okPct}%` }} />}</div>
      <div className="pr-timeline-bottom"><span>Registro: {fmtFecha(f.fecha_registro)}</span><b>Límite interno: {fmtFecha(f.fecha_limite_interna)}</b><span className={a.dias > 0 ? "red-text" : ""}>Atención: {fmtFecha(f.fecha_atencion)}</span></div>
    </div>}
    <div className="pr-foot">
      <span>{f.limitacion_de_la_evaluacion}</span>
      <div className="pr-actions">
        <button className="pr-btn ghost" type="button" onClick={onAbrir}>👁 Ver expediente</button>
        <button className="pr-btn ghost" type="button" disabled={enviando} onClick={() => onRevisar(false)}>⊗ Descartar falso positivo</button>
        <button className="pr-btn dark" type="button" disabled={enviando} onClick={() => onRevisar(true)}>{enviando ? "Registrando…" : "⛨ Confirmar alerta"}</button>
      </div>
    </div>
  </article>;
}

function ObligacionCard({ o }: { o: ReportItem }) {
  const t = o.estado === "atrasado" ? "red" : "amber";
  const [mn, mx] = o.rango_uit;
  const [smn, smx] = o.rango_soles;
  return <article className={`pr-card small ${t}`}>
    <div className="pr-small-top"><span className={`pr-badge ${t}-soft`}>{o.estado === "atrasado" ? "Obligación vencida" : "Obligación por vencer"}</span><span className="pr-muted">{o.dias_atraso > 0 ? `+${o.dias_atraso} días` : ""}</span></div>
    <div className="pr-small-title"><code>{o.obligacion.codigo}</code><h3>{o.obligacion.accion_requerida}</h3></div>
    <p>{o.obligacion.norma_codigo}, art. {o.obligacion.articulo_numero} (versión {o.obligacion.version_id}). {o.casos.filter((c) => c.estado !== "cumplido").map((c) => `${c.sujeto_id ?? "caso"}: ${c.estado}${c.fecha_limite ? `, límite ${fmtFecha(c.fecha_limite)}` : ""}`).join(" · ")}</p>
    <div className="pr-small-foot"><span>{o.infracciones.length ? `Infracción ${o.infracciones.map((i) => `${i.infraccion.codigo_numeral ?? ""}${i.sintetica ? " [SINTÉTICA]" : ""}`).join(", ")}` : "Sin infracción validada enlazada"}</span>
      <span className="pr-mono-blue">{mn == null && mx == null ? "Monto no determinado" : `${mn ?? "?"}–${mx ?? "?"} UIT${smx != null ? ` (${soles(smn)}–${soles(smx)})` : ""}`}</span></div>
    <small className="pr-muted">Exposición potencial, no sanción determinada.</small>
  </article>;
}
