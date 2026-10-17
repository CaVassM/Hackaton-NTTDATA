import { useState } from "react";

/* MOCKUP de la propuesta: datos estáticos, sin conexión al backend. */

const KPIS = [
  { label: "Total alertas activas", value: "23", extra: <span className="pr-trend">↗ +3 hoy</span>, foot: null, bar: 72, icon: "●", iconTone: "red" },
  { label: "Incumplimiento normativo", value: "14", extra: <span className="pr-tag red">Crítica / Alta</span>, foot: "60.8% del total de incidencias", icon: "⚖" },
  { label: "Vencimiento de plazos", value: "9", extra: <span className="pr-tag amber">Excedidos</span>, foot: "Promedio: +2.8 días hábiles", icon: "⏰" },
  { label: "Falsos positivos IA", value: "2.1%", extra: <span className="pr-link-text">Grounding 97.9%</span>, foot: "✓ Calibración RAG óptima", icon: "✦" },
  { label: "Tiempo prom. resolución", value: "3.4", extra: <span className="pr-link-text">−42 min vs SLA</span>, foot: "SLA corporativo: < 5.0 hrs", suffix: "hrs", icon: "◔" },
];

const TABS: Array<[string, number | null, string]> = [
  ["Todas las alertas", 23, ""],
  ["Incumplimiento normativo", 14, "red"],
  ["Vencimiento de plazos", 9, "amber"],
  ["En subsanación", 6, "blue"],
  ["Historial resueltas", null, ""],
];

const SMALL = [
  { tone: "red", tag: "Incumplimiento normativo", side: "Severidad media", id: "CAS-2024-0968", title: "Cifrado y transferencia de datos en nube sin acreditación", body: <>Infracción a <b>Ley 29733 Cap. IV Art. 8</b>. El proveedor de nube no cuenta con certificación ISO/IEC 27018 indexada en el repositorio legal.</>, who: "Ing. Carlos Paredes", meta: "RAG Match: 88.7%", actions: ["Ver expediente", "Dictaminar"] },
  { tone: "amber", tag: "Término regulatorio", side: "+1 día hábil exceso", id: "CAS-2024-0952", title: "Límite de posición cambiaria intradía sin cierre", body: <>Exceso sobre circular BCRP de Tesorería. Reporte diario de sobregiro cambiario spot no consolidado en ventanilla regulatoria.</>, who: "Dra. Claudia Medina", meta: "Cierre exigido: ayer 18:00", actions: ["Requerir descargo", "Dictaminar"] },
];

const QUEUE = [
  { id: "CAS-2024-0941", tone: "red", type: "Normativa material", norm: "Ley 29733 Art. 12 (Supresión de datos)", agent: "Lic. Marcos Benítez", conf: "96.1%", state: ["En revisión", "amber"], action: "Evaluar" },
  { id: "CAS-2024-0938", tone: "amber", type: "Vencimiento término", norm: "SBS Circular G-184 (+2 días)", agent: "Dra. Gabriela Soto", conf: "N/A (algorítmico)", state: ["Vencido", "red"], action: "Notificar" },
  { id: "CAS-2024-0925", tone: "red", type: "Normativa material", norm: "Res. BCRP 019-2021 (Encaje mínimo)", agent: "Dra. Claudia Medina", conf: "91.4%", state: ["Subsanando", "blue"], action: "Inspeccionar" },
  { id: "CAS-2024-0917", tone: "red", type: "Normativa material", norm: "Res. SBS N° 2660-2015 Art. 49 (Registro de operaciones)", agent: "Ing. Carlos Paredes", conf: "93.8%", state: ["En revisión", "amber"], action: "Evaluar" },
];

export default function ProposalPage() {
  const [tab, setTab] = useState(0);
  return <section className="page pr">
    <div className="pr-hero">
      <div>
        <div className="pr-eyebrow"><span className="pr-badge red">SUPERVISIÓN CRÍTICA ACTIVA</span><span className="pr-eyebrow-text">• Motor RAG v2.4 (SBS & BCRP Compliance)</span></div>
        <h1>Centro de Alertas Inteligentes y Vigilancia de Plazos</h1>
        <p>Clasificación automatizada mediante motor RAG discriminando incumplimientos normativos materiales y vencimientos de términos legales perentorios.</p>
      </div>
      <div className="pr-hero-actions">
        <button className="pr-btn light" type="button">⚙ Ajustar umbrales RAG</button>
        <button className="pr-btn soft" type="button">✓✓ Marcar seleccionadas</button>
        <button className="pr-btn dark" type="button">⬇ Exportar reporte (XLS/PDF)</button>
      </div>
    </div>

    <div className="pr-kpis">
      {KPIS.map((k) => <article className="pr-kpi" key={k.label}>
        <header><span>{k.label}</span><i className={k.iconTone ?? ""}>{k.icon}</i></header>
        <div className="pr-kpi-main"><strong>{k.value}</strong>{k.suffix && <em>{k.suffix}</em>}{k.extra}</div>
        {k.foot && <small>{k.foot}</small>}
        {k.bar != null && <div className="pr-kpi-bar"><span style={{ width: `${k.bar}%` }} /></div>}
      </article>)}
    </div>

    <div className="pr-filters">
      <div className="pr-tabs">
        {TABS.map(([label, n, tone], i) => <button key={label} type="button" className={`${i === tab ? "active" : ""} ${tone}`} onClick={() => setTab(i)}>{tone && <span className={`pr-dot ${tone}`} />}{label}{n != null && <b>{n}</b>}</button>)}
      </div>
      <div className="pr-fields">
        <input placeholder="🔍 Buscar caso (ej. CAS-2024), término, normativa…" aria-label="Buscar" />
        <select aria-label="Agente"><option>Agente responsable</option><option>Lic. Marcos Benítez</option><option>Dra. Gabriela Soto</option><option>Ing. Carlos Paredes</option></select>
        <select aria-label="Resolución"><option>Resolución / Entidad</option><option>SBS</option><option>BCRP</option><option>SMV</option></select>
        <select aria-label="Severidad"><option>Severidad: Todas</option><option>Crítica</option><option>Alta</option><option>Media</option></select>
        <select aria-label="Revisión"><option>Revisión: Pendiente</option><option>En revisión</option><option>Resuelta</option></select>
      </div>
    </div>

    <article className="pr-card red">
      <div className="pr-card-head">
        <span className="pr-badge red-soft">● Incumplimiento normativo material</span><code>CAS-2024-0981</code><span className="pr-sep">•</span><h2>Contrato de apertura digital sin consentimiento expreso</h2>
      </div>
      <div className="pr-card-head sub"><span className="pr-outline red">SEVERIDAD CRÍTICA</span><span className="pr-outline blue mono">◎ RAG Grounding: 94.2%</span></div>
      <div className="pr-info">
        <div><label>Agente responsable</label><strong>◉ Lic. Marcos Benítez</strong><small>División Banca Corporativa Lima</small></div>
        <div><label>Normativa infringida</label><strong>▤ Res. SBS N° 1134-2023</strong><small>Art. 45.2 ‘Condiciones contractuales previas y consentimiento’</small></div>
        <div><label>Detección y cómputo</label><strong>◔ Hace 42 minutos</strong><small>Vía ingesta OCR + pipeline embeddings #CHUNK-412</small></div>
      </div>
      <div className="pr-finding">
        <div className="pr-finding-head"><b>▥ Hallazgo semántico automatizado por IA</b><code>Vector ID: sbs-1134-v2-dim1536</code></div>
        <p>“El texto del contrato carece de la cláusula mandatoria de autorización expresa para cesión interbancaria de datos. Similitud semántica de omisión: <b className="red-text">94.2%</b> frente al estándar SBS.”</p>
        <div className="pr-compare">
          <div><header><b>▤ Documento analizado (PDF pág. 4, cláusula 12)</b><code>SHA-256: 4fa9…d82b</code></header><blockquote>“…el cliente autoriza el tratamiento general de información personal según políticas web institucionales vigentes…” <span className="red-text">[Ausencia de casilla desmarcada y mención explícita a entidades del Grupo]</span></blockquote></div>
          <div><header><b>◈ Exigencia mandatoria SBS (chunk #00412)</b><code>Art. 45.2 párrafo 3</code></header><blockquote>“…la autorización para cesión de datos crediticios o sensibles requerirá manifestación de voluntad indubitable, específica y en documento o acápite independiente…”</blockquote></div>
        </div>
      </div>
      <div className="pr-foot">
        <span>◔ Plazo de subsanación regulatoria: <b>48 hrs hábiles restantes</b></span>
        <div className="pr-actions"><button className="pr-btn ghost" type="button">👁 Ver detalle del caso</button><button className="pr-btn ghost" type="button">⊗ Descartar falso positivo</button><button className="pr-btn ghost" type="button">✉ Solicitar subsanación</button><button className="pr-btn dark" type="button">⛨ Confirmar incumplimiento & dictaminar</button></div>
      </div>
    </article>

    <article className="pr-card amber">
      <div className="pr-card-head">
        <span className="pr-badge amber-soft">● Término legal perentorio vencido</span><code>CAS-2024-0899</code><span className="pr-sep">•</span><h2>Informe pericial de riesgo operativo no remitido a SMV</h2>
      </div>
      <div className="pr-card-head sub"><span className="pr-outline red">URGENCIA ALTA</span><span className="pr-badge red-soft mono">+4 días hábiles de retraso</span></div>
      <div className="pr-info">
        <div><label>Agente a cargo</label><strong>◉ Dra. Gabriela Soto</strong><small>Unidad Especial de Cumplimiento AML</small></div>
        <div><label>Mandato regulatorio</label><strong>▤ Res. SMV 005-2022</strong><small>Art. 18 (plazo perentorio improrrogable: 30 días hábiles)</small></div>
        <div><label>Cómputo temporal exacto</label><strong>12 ago 2024 → <span className="red-text">24 sep 2024 (límite)</span></strong><small>Infracción tipificada como grave</small></div>
      </div>
      <div className="pr-timeline">
        <div className="pr-timeline-top"><span>Línea temporal de cómputo perentorio</span><b className="red-text">34 de 30 días hábiles consumidos (113%)</b></div>
        <div className="pr-track"><span className="ok" style={{ width: "88%" }} /><span className="over" style={{ width: "12%" }} /></div>
        <div className="pr-timeline-bottom"><span>Inicio: notificación electrónica</span><b>Vencimiento formal: 24/09/2024</b><span className="red-text">Fecha actual: +4 días en infracción</span></div>
      </div>
      <div className="pr-foot">
        <span>🔔 Notificaciones emitidas al agente: <b>3 recordatorios</b></span>
        <div className="pr-actions"><button className="pr-btn ghost" type="button">✎ Registrar justificación</button><button className="pr-btn ghost" type="button">✉ Notificar al agente</button><button className="pr-btn dark" type="button">⚑ Elevar a Comité de Sanciones</button></div>
      </div>
    </article>

    <div className="pr-pair">
      {SMALL.map((c) => <article className={`pr-card small ${c.tone}`} key={c.id}>
        <div className="pr-small-top"><span className={`pr-badge ${c.tone}-soft`}>{c.tag}</span><span className="pr-muted">{c.side}</span></div>
        <div className="pr-small-title"><code>{c.id}</code><h3>{c.title}</h3></div>
        <p>{c.body}</p>
        <div className="pr-small-foot"><span>◉ {c.who}</span><span className="pr-mono-blue">{c.meta}</span></div>
        <div className="pr-actions end">{c.actions.map((a, i) => <button key={a} type="button" className={`pr-btn ${i ? "dark" : "ghost"} sm`}>{a}</button>)}</div>
      </article>)}
    </div>

    <article className="pr-queue">
      <div className="pr-queue-head"><div><h2>Cola de vigilancia continua</h2><p>Alertas de menor impacto o en espera de validación de chunks vectoriales adicionales.</p></div><b>Mostrando 4 de 23 expedientes</b></div>
      <div className="pr-table-wrap"><table>
        <thead><tr><th>Caso</th><th>Tipología</th><th>Normativa / plazo</th><th>Agente asignado</th><th>Confianza RAG</th><th>Estado</th><th>Acción rápida</th></tr></thead>
        <tbody>{QUEUE.map((q) => <tr key={q.id}>
          <td><code>{q.id}</code></td>
          <td><span className={`pr-dot ${q.tone}`} /> {q.type}</td>
          <td className="pr-muted">{q.norm}</td>
          <td><b>{q.agent}</b></td>
          <td className="pr-mono-blue">{q.conf}</td>
          <td><span className={`pr-state ${q.state[1]}`}>{q.state[0]}</span></td>
          <td><button type="button" className="pr-link">{q.action}</button></td>
        </tr>)}</tbody>
      </table></div>
    </article>
    <p className="pr-note">Vista de propuesta (maqueta con datos de ejemplo, sin conexión al backend).</p>
  </section>;
}
