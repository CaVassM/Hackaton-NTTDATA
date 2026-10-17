import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { api, CaseResult, CaseSchema, CaseSummary, Citation, ExpedienteBatchItem, Health, SearchResult } from "./api";
import "./import.css";

type View = "dashboard" | "cases" | "rag" | "alerts" | "detail";
type Notice = { kind: "error" | "success"; text: string } | null;

const menu: Array<{ id: View; icon: string; label: string }> = [
  { id: "dashboard", icon: "▦", label: "Dashboard principal" },
  { id: "cases", icon: "✓", label: "Gestión de casos" },
  { id: "rag", icon: "⌘", label: "Motor RAG y evaluación IA" },
  { id: "alerts", icon: "◉", label: "Centro de alertas" },
];

const today = (() => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
})();

const IMPORT_CHUNK_SIZE = 40;
type BatchAssessment = { label: string; tone: string; detail: string; source: string; priority: string };

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  const source = text.replace(/^\uFEFF/, "");
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === '"') {
      if (quoted && source[index + 1] === '"') { field += '"'; index += 1; }
      else quoted = !quoted;
    } else if (!quoted && char === ",") {
      row.push(field); field = "";
    } else if (!quoted && (char === "\n" || char === "\r")) {
      if (char === "\r" && source[index + 1] === "\n") index += 1;
      row.push(field);
      if (row.some((value) => value.trim())) rows.push(row);
      row = []; field = "";
    } else field += char;
  }
  if (quoted) throw new Error("El CSV tiene comillas sin cerrar.");
  row.push(field);
  if (row.some((value) => value.trim())) rows.push(row);
  if (rows.length < 2) throw new Error("El CSV debe tener encabezados y al menos un caso.");
  const headers = rows[0].map((value) => value.trim());
  const required = ["id_caso", "descripcion_caso"];
  const missing = required.filter((name) => !headers.includes(name));
  if (missing.length) throw new Error(`Faltan columnas obligatorias: ${missing.join(", ")}.`);
  if (new Set(headers).size !== headers.length || headers.some((value) => !value)) {
    throw new Error("Los encabezados deben tener nombres unicos y no pueden estar vacios.");
  }
  const badRow = rows.slice(1).findIndex((values) => values.length !== headers.length);
  if (badRow >= 0) throw new Error(`La fila ${badRow + 2} tiene ${rows[badRow + 1].length} columnas; se esperaban ${headers.length}.`);
  return rows;
}

function csvText(rows: string[][]): string {
  return rows.map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(",")).join("\r\n");
}

function assessExpediente(item: ExpedienteBatchItem): BatchAssessment {
  if (!item.ok || !item.result) {
    return { label: "No evaluado", tone: "warn", detail: item.error || "No se obtuvo resultado.", source: "—", priority: "—" };
  }
  const row = item.result.fila;
  const result = String(row.resultado_esperado ?? "");
  const source = String(row.fuente_legal ?? "");
  const priority = String(row.prioridad ?? "—");
  if (result === "POSIBLE_INCUMPLIMIENTO") {
    const reason = String(row.por_que_si_o_no ?? "Se detectaron señales que requieren revisión.");
    const limitation = String(row.limitacion_de_la_evaluacion ?? "");
    return { label: "Posible incumplimiento", tone: "danger", detail: [reason, limitation].filter(Boolean).join(" "), source, priority };
  }
  if (result === "SIN_INCUMPLIMIENTO_DETECTADO") {
    return { label: "Sin indicios detectados", tone: "good", detail: String(row.por_que_si_o_no ?? ""), source, priority };
  }
  return { label: "Información insuficiente", tone: "warn", detail: String(row.por_que_si_o_no ?? "No hay datos suficientes para evaluar."), source, priority };
}

function downloadCsv(name: string, rows: string[][]) {
  const blob = new Blob([`\uFEFF${csvText(rows)}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = name; link.click();
  URL.revokeObjectURL(url);
}

function stateLabel(state?: string | null) {
  const value = state ?? "sin decisión";
  return value.replaceAll("_", " ");
}

function Pill({ value, tone }: { value?: string | null; tone?: string }) {
  const valueTone = tone ?? (/allow|cumplido|validada|ok/i.test(value ?? "") ? "good" : /block|atrasado|alto|error|rechazada/i.test(value ?? "") ? "danger" : "warn");
  return <span className={`pill ${valueTone}`}>{stateLabel(value)}</span>;
}

function formatMoney(value?: number | null) {
  return value == null ? "No determinado" : new Intl.NumberFormat("es-PE", { style: "currency", currency: "PEN", maximumFractionDigits: 0 }).format(value);
}

function CitationCard({ citation }: { citation: Citation }) {
  return <div className="citation">
    <div><strong>{citation.norma}</strong> · Art. {citation.articulo}</div>
    <small>Versión {citation.version_id} · vigente desde {citation.vigente_desde}{citation.vigente_hasta ? ` hasta ${citation.vigente_hasta}` : ""}</small>
  </div>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export default function App() {
  const [view, setView] = useState<View>("dashboard");
  const [health, setHealth] = useState<Health | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selected, setSelected] = useState<CaseResult | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    const [healthResult, caseResult] = await Promise.allSettled([api.health(), api.cases()]);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (caseResult.status === "fulfilled") setCases(caseResult.value);
    const failure = healthResult.status === "rejected" ? healthResult.reason : caseResult.status === "rejected" ? caseResult.reason : null;
    if (failure) setNotice({ kind: "error", text: `No se pudo conectar al backend: ${failure.message}. Inícialo en el puerto 8000.` });
    setLoading(false);
  };

  useEffect(() => { void refresh(); }, []);

  const openCase = async (id: string) => {
    try {
      setLoading(true);
      setSelected(await api.case(id));
      setView("detail");
    } catch (error) { setNotice({ kind: "error", text: (error as Error).message }); }
    finally { setLoading(false); }
  };

  const navigate = (next: View) => { setView(next); setNotice(null); };

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">R</div><div><strong>RAG Compliance</strong><small>IA & vigilancia normativa</small></div></div>
      <div className="sidebar-rule" />
      <nav aria-label="Navegación principal">
        {menu.map((item) => <button key={item.id} onClick={() => navigate(item.id)} className={view === item.id || (item.id === "cases" && view === "detail") ? "nav-item active" : "nav-item"}><span>{item.icon}</span>{item.label}</button>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="side-status"><span className={health?.status === "ok" ? "online" : "offline"} />{health?.status === "ok" ? "Servicios operativos" : "Estado por verificar"}</div>
        <button className="nav-item" onClick={() => void refresh()}><span>↻</span>Actualizar datos</button>
      </div>
    </aside>
    <div className="main-area">
      <header className="topbar"><div><span className="eyebrow">SUPERVISIÓN REGULATORIA</span><strong>Centro de cumplimiento LA/FT</strong></div><div className="topbar-actions"><span className="live"><i /> Motor RAG local</span><button className="icon-button" aria-label="Actualizar" onClick={() => void refresh()}>↻</button><div className="avatar">EV</div></div></header>
      <main>
        {notice && <div className={`notice ${notice.kind}`} role="status"><span>{notice.kind === "error" ? "!" : "✓"}</span>{notice.text}<button aria-label="Cerrar" onClick={() => setNotice(null)}>×</button></div>}
        {loading && <div className="loading-line" />}
        {view === "dashboard" && <Dashboard health={health} cases={cases} openCase={openCase} go={navigate} />}
        {view === "cases" && <CasesPage cases={cases} onOpen={openCase} onImported={() => { void refresh(); }} onCreated={(result) => { setSelected(result); setCases((old) => [{ case_id: result.case.case_id, tipo_evento: result.case.tipo_evento, decision: result.audit_result?.decision ?? null, evaluado_en: result.evaluado_en }, ...old.filter((entry) => entry.case_id !== result.case.case_id)]); setView("detail"); setNotice({ kind: "success", text: "Caso evaluado y registrado correctamente." }); }} />}
        {view === "detail" && <CaseDetail result={selected} onBack={() => setView("cases")} />}
        {view === "rag" && <RagPage />}
        {view === "alerts" && <AlertsPage />}
      </main>
    </div>
  </div>;
}

function Dashboard({ health, cases, openCase, go }: { health: Health | null; cases: CaseSummary[]; openCase: (id: string) => void; go: (view: View) => void }) {
  const indexed = health?.bases.rag?.versiones_sql ?? 0;
  return <section className="page"><div className="page-heading"><div><span className="eyebrow">PANEL DE CONTROL</span><h1>Inteligencia de cumplimiento</h1><p>Vigilancia regulatoria, evaluación trazable de expedientes y respuestas sustentadas en normativa SBS.</p></div><button className="primary" onClick={() => go("cases")}>+ Evaluar caso</button></div>
    <div className="metrics">
      <Metric label="Estado del backend" value={health ? health.status : "Conectando"} detail={health ? `API v${health.version}` : "Verificando servicios"} tone={health?.status === "ok" ? "good" : "warn"} />
      <Metric label="Versiones RAG indexadas" value={String(indexed)} detail="Base normativa disponible" />
      <Metric label="Casos evaluados" value={String(cases.length)} detail="Últimos registros persistidos" />
      <Metric label="Política de auditoría" value={health?.policy_version ?? "—"} detail={`Modo: ${health?.audit_mode ?? "—"}`} />
    </div>
    <div className="two-col"><article className="panel"><div className="panel-title"><div><h2>Actividad reciente</h2><p>Resultados recuperados desde la API de casos.</p></div><button className="text-button" onClick={() => go("cases")}>Ver todos →</button></div>{cases.length ? <CaseTable cases={cases.slice(0, 6)} onOpen={openCase} /> : <Empty>Aún no hay casos evaluados. Crea el primero desde Gestión de casos.</Empty>}</article>
      <article className="panel"><div className="panel-title"><div><h2>Salud operativa</h2><p>Dependencias del procesamiento local.</p></div></div>{health ? <div className="health-list"><HealthRow label="Ollama" value={health.ollama.reachable ? "Disponible" : "No disponible"} ok={health.ollama.reachable} />{Object.entries(health.ollama.models).map(([model, available]) => <HealthRow key={model} label={model} value={available ? "Cargado" : "Pendiente"} ok={available} />)}<HealthRow label="Cadena de auditoría" value={health.bases.audit ? "Verificada por backend" : "Sin datos"} ok={Boolean(health.bases.audit)} /></div> : <Empty>Esperando respuesta de /health.</Empty>}</article></div>
  </section>;
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: string }) { return <article className="metric"><span>{label}</span><strong className={tone}>{value}</strong><small>{detail}</small></article>; }
function HealthRow({ label, value, ok }: { label: string; value: string; ok: boolean }) { return <div className="health-row"><span><i className={ok ? "online" : "offline"} />{label}</span><Pill value={value} tone={ok ? "good" : "danger"} /></div>; }

function CaseTable({ cases, onOpen }: { cases: CaseSummary[]; onOpen: (id: string) => void }) { return <div className="table-wrap"><table><thead><tr><th>Identificador</th><th>Evento</th><th>Decisión</th><th>Evaluado</th><th /></tr></thead><tbody>{cases.map((item) => <tr key={item.case_id}><td><code>{item.case_id}</code></td><td>{stateLabel(item.tipo_evento)}</td><td><Pill value={item.decision} /></td><td>{new Date(item.evaluado_en).toLocaleDateString("es-PE")}</td><td><button className="row-button" onClick={() => void onOpen(item.case_id)}>Revisar</button></td></tr>)}</tbody></table></div>; }

function CasesPage({ cases, onOpen, onCreated, onImported }: { cases: CaseSummary[]; onOpen: (id: string) => void; onCreated: (result: CaseResult) => void; onImported: () => void }) {
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [schema, setSchema] = useState<CaseSchema | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  useEffect(() => { void api.caseSchema().then(setSchema).catch((reason) => setSchemaError((reason as Error).message)); }, []);
  return <section className="page">
    <div className="page-heading"><div><span className="eyebrow">EXPEDIENTES OFICIALES</span><h1>Gestión integral de casos</h1><p>Registra eventos, evalúa obligaciones y conserva la trazabilidad de la auditoría.</p></div><div className="page-actions"><button className="secondary" onClick={() => setShowImport((visible) => !visible)}>{showImport ? "Cerrar importación" : "Importar CSV"}</button><button className="primary" onClick={() => setShowForm((visible) => !visible)}>{showForm ? "Cerrar formulario" : "+ Nuevo caso"}</button></div></div>
    {schemaError && <div className="notice error">No se pudo cargar el catálogo de eventos: {schemaError}</div>}
    {showImport && <ExpedienteImport onImported={onImported} />}
    {showForm && <CaseForm eventTypes={schema?.tipos_evento ?? {}} onSuccess={onCreated} />}
    <article className="panel"><div className="panel-title"><div><h2>Registro central</h2><p>Última evaluación por caso.</p></div><span className="counter">{cases.length} casos</span></div>{cases.length ? <CaseTable cases={cases} onOpen={onOpen} /> : <Empty>No hay expedientes en la base todavia.</Empty>}</article>
  </section>;
}

function ExpedienteImport({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [results, setResults] = useState<ExpedienteBatchItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const assessments = results.map(assessExpediente);
  const possibleCount = assessments.filter((item) => item.label === "Posible incumplimiento").length;
  const insufficientCount = assessments.filter((item) => item.label === "Información insuficiente").length;
  const missingNormCount = assessments.filter((item) => item.source.includes("NO_DISPONIBLE_EN_CORPUS")).length;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) return;
    setImporting(true); setError(null); setResults([]); setProgress({ done: 0, total: 0 });
    let completed = 0;
    try {
      const rows = parseCsv(await file.text());
      const headers = rows[0];
      const records = rows.slice(1);
      setProgress({ done: 0, total: records.length });
      for (let offset = 0; offset < records.length; offset += IMPORT_CHUNK_SIZE) {
        const chunk = records.slice(offset, offset + IMPORT_CHUNK_SIZE);
        const part = new File([csvText([headers, ...chunk])], `lote-${Math.floor(offset / IMPORT_CHUNK_SIZE) + 1}.csv`, { type: "text/csv" });
        const batch = await api.importExpedientesCsv(part);
        setResults((previous) => [...previous, ...batch]);
        completed += chunk.length;
        setProgress({ done: completed, total: records.length });
      }
      onImported();
    } catch (reason) {
      setError(`${completed ? `Se procesaron ${completed} casos antes del error. ` : ""}${(reason as Error).message}`);
      if (completed) onImported();
    } finally { setImporting(false); }
  };

  const exportResults = () => {
    const rows: string[][] = [["id_caso", "resultado", "prioridad", "explicacion", "fuente_legal", "revision_humana"]];
    results.forEach((item) => {
      const row = item.result?.fila ?? {};
      const assessment = assessExpediente(item);
      rows.push([item.id_caso ?? "", assessment.label, assessment.priority, assessment.detail,
        assessment.source, String(row.revision_humana ?? "PENDIENTE")]);
    });
    downloadCsv("resultados_revision_expedientes.csv", rows);
  };

  return <article className="panel import-panel">
    <div className="panel-title"><div><h2>Importar y revisar expedientes</h2><p>Sube un CSV para detectar señales por caso y descargar el resultado completo.</p></div>{results.length > 0 && <button className="text-button" onClick={exportResults}>Descargar resultados CSV</button>}</div>
    <p className="import-guidance">Columnas obligatorias: <code>id_caso</code>, <code>descripcion_caso</code>. Fechas opcionales: <code>fecha_registro</code>, <code>fecha_limite_interna</code>, <code>fecha_atencion</code>. El archivo se procesa en bloques de {IMPORT_CHUNK_SIZE} casos.</p>
    <p className="import-warning">La clasificación marca posibles indicios para revisión; no determina responsabilidad legal. Consulta los artículos 1-4 vigentes del D. Leg. 1106, modificados por la Ley 31178.</p>
    <form onSubmit={submit}><div className="import-controls"><label className="file-label">Archivo CSV<input type="file" accept=".csv,text/csv" onChange={(event) => { setFile(event.currentTarget.files?.[0] ?? null); setResults([]); setError(null); }} /></label><button type="button" className="text-button" onClick={() => downloadCsv("plantilla_expedientes.csv", [["id_caso", "descripcion_caso", "fecha_registro", "fecha_limite_interna", "fecha_atencion"], ["EXP-001", "Descripcion completa del expediente con los hechos y soportes conocidos.", "", "", ""]])}>Descargar plantilla</button><button className="primary" disabled={!file || importing}>{importing ? `Evaluando ${progress.done}/${progress.total || "?"}` : "Importar y evaluar"}</button></div></form>
    {progress.total > 0 && <div className="import-progress" role="status">Procesados {progress.done} de {progress.total} casos.</div>}
    {error && <div className="form-error">{error}</div>}
    {results.length > 0 && <><div className="batch-summary"><span><strong>{possibleCount}</strong> posibles incumplimientos</span><span><strong>{insufficientCount}</strong> con información insuficiente</span><span><strong>{missingNormCount}</strong> sin cita normativa cargada</span></div><div className="table-wrap batch-table"><table><thead><tr><th>Caso</th><th>Resultado</th><th>Prioridad</th><th>Fundamento / fuente</th><th>Explicación</th></tr></thead><tbody>{results.map((item, index) => { const assessment = assessExpediente(item); const sourceMissing = assessment.source.includes("NO_DISPONIBLE_EN_CORPUS"); return <tr key={`${item.id_caso ?? "sin-id"}-${index}`}><td><code>{item.id_caso ?? "?"}</code></td><td><Pill value={assessment.label} tone={assessment.tone} /></td><td>{assessment.priority}</td><td>{sourceMissing ? "Texto aplicable no disponible en el corpus" : assessment.source}</td><td className="batch-detail">{assessment.detail}</td></tr>; })}</tbody></table></div></>}
  </article>;
}

function CaseForm({ eventTypes, onSuccess }: { eventTypes: CaseSchema["tipos_evento"]; onSuccess: (result: CaseResult) => void }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setSubmitting(true); setError(null); const data = new FormData(event.currentTarget); const payload = { case_id: String(data.get("case_id")), user_id: String(data.get("user_id")), rol: String(data.get("rol")), tipo_evento: String(data.get("tipo_evento")), fecha_evento: String(data.get("fecha_evento")), fecha_cumplimiento: String(data.get("fecha_cumplimiento")) || null, monto: data.get("monto") ? Number(data.get("monto")) : null, moneda: "PEN", descripcion: String(data.get("descripcion")) || null }; try { onSuccess(await api.evaluateCase(payload)); } catch (reason) { setError((reason as Error).message); } finally { setSubmitting(false); } };
  return <form className="case-form panel" onSubmit={submit}><div className="panel-title"><div><h2>Nuevo evento de cumplimiento</h2><p>Los campos se validan contra el contrato de <code>/cases/evaluate</code>.</p></div></div>{error && <p className="form-error">{error}</p>}<div className="form-grid"><label>ID del caso<input required name="case_id" placeholder="ROS-2026-0115" pattern="[A-Za-z0-9._-]+" /></label><label>Usuario responsable<input required name="user_id" defaultValue="analista.01" /></label><label>Rol<select name="rol" defaultValue="analista"><option value="analista">Analista</option><option value="oficial_cumplimiento">Oficial de cumplimiento</option></select></label><label>Tipo de evento<select required name="tipo_evento" defaultValue="" disabled={!Object.keys(eventTypes).length}><option value="" disabled>Selecciona un evento</option>{Object.entries(eventTypes).map(([type, info]) => <option key={type} value={type}>{type.replaceAll("_", " ")} — {info.descripcion}</option>)}</select></label><label>Fecha del evento<input required type="date" name="fecha_evento" defaultValue={today} /></label><label>Fecha de cumplimiento<input type="date" name="fecha_cumplimiento" /></label><label>Monto (PEN)<input type="number" min="0" step="0.01" name="monto" placeholder="185000" /></label><label className="wide">Descripción<textarea name="descripcion" maxLength={2000} placeholder="Describe los hechos relevantes y la evidencia disponible." /></label></div><div className="form-actions"><span>{Object.keys(eventTypes).length ? "Eventos y roles disponibles desde /cases/schema." : "Cargando catálogo de eventos…"}</span><button className="primary" disabled={submitting || !Object.keys(eventTypes).length}>{submitting ? "Evaluando…" : "Evaluar con RAG"}</button></div></form>;
}

function CaseDetail({ result, onBack }: { result: CaseResult | null; onBack: () => void }) {
  if (!result) return <section className="page"><button className="text-button" onClick={onBack}>← Volver a casos</button><Empty>Selecciona un caso del registro para consultar su dictamen.</Empty></section>;
  const decision = result.audit_result?.decision ?? (result.publicable ? "publicable" : "pendiente");
  return <section className="page"><button className="text-button back" onClick={onBack}>← Gestión de casos</button><div className="page-heading compact"><div><span className="eyebrow">DICTAMEN Y TRAZABILIDAD</span><h1>{result.case.case_id}</h1><p>{result.evento_descripcion}</p></div><div className="decision"><Pill value={decision} /><small>Evaluado: {new Date(result.evaluado_en).toLocaleString("es-PE")}</small></div></div>
    <div className="detail-grid"><article className="panel"><div className="panel-title"><h2>Información del caso</h2></div><dl className="data-list"><dt>Responsable</dt><dd>{result.case.user_id} · {stateLabel(result.case.rol)}</dd><dt>Evento</dt><dd>{stateLabel(result.case.tipo_evento)}</dd><dt>Fecha</dt><dd>{result.case.fecha_evento}</dd><dt>Monto</dt><dd>{result.case.monto != null ? `${result.case.moneda} ${result.case.monto.toLocaleString("es-PE")}` : "No declarado"}</dd></dl><p className="case-description">{result.case.descripcion || "Sin descripción adicional."}</p></article><article className="panel highlight"><div className="panel-title"><h2>Conclusión asistida</h2><Pill value={result.resumen_origen} tone="neutral" /></div><p className="summary">{result.resumen}</p>{result.advertencias.length > 0 && <ul className="warnings">{result.advertencias.map((warning) => <li key={warning}>{warning}</li>)}</ul>}</article></div>
    <div className="two-col wide-left"><article className="panel"><div className="panel-title"><div><h2>Obligaciones y fundamento</h2><p>Hallazgos obtenidos desde normas indexadas.</p></div></div>{result.obligaciones.length ? <div className="finding-list">{result.obligaciones.map((item) => <div className="finding" key={item.codigo}><div className="finding-title"><code>{item.codigo}</code><Pill value={item.estado_validacion} /></div><strong>{item.accion_requerida ?? "Obligación identificada"}</strong><p>{item.sujeto && `${item.sujeto}. `}{item.plazo_texto && `Plazo: ${item.plazo_texto}. `}{item.cita_textual}</p>{item.cita && <CitationCard citation={item.cita} />}</div>)}</div> : <Empty>No se encontraron obligaciones validadas para este caso.</Empty>}</article><article className="panel"><div className="panel-title"><h2>Plazos y exposición</h2></div>{result.plazos.map((item) => <div className="deadline" key={`${item.obligacion_codigo}-${item.estado}`}><div><strong>{item.obligacion_codigo}</strong><small>{item.detalle || "Sin detalle"}</small></div><Pill value={item.estado} /></div>)}{result.exposicion.map((item) => <div className="exposure" key={`${item.obligacion_codigo}-${item.descripcion}`}><Pill value={item.gravedad ?? "sin gravedad"} /><strong>{item.descripcion}</strong><small>{item.infraccion_numeral ?? "Sin numeral"} · {formatMoney(item.max_soles)} máximo potencial</small></div>)}{!result.plazos.length && !result.exposicion.length && <Empty>Sin plazos ni exposición aplicable.</Empty>}</article></div>
  </section>;
}

function RagPage() {
  const [query, setQuery] = useState(""); const [date, setDate] = useState(""); const [includeProjects, setIncludeProjects] = useState(false); const [result, setResult] = useState<SearchResult | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const submit = async (event: FormEvent) => { event.preventDefault(); if (query.trim().length < 2) return; setLoading(true); setError(null); try { setResult(await api.search({ query: query.trim(), fecha: date || undefined, top_k: 5, incluir_proyectos: includeProjects })); } catch (reason) { setError((reason as Error).message); } finally { setLoading(false); } };
  return <section className="page"><div className="page-heading"><div><span className="eyebrow">BASE NORMATIVA SBS</span><h1>Motor RAG y evaluación IA</h1><p>Consulta normativa con fecha de vigencia y citas de la versión aplicable.</p></div></div><form className="search-panel panel" onSubmit={submit}><label className="search-label">Pregunta normativa<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="¿Cuál es el plazo para atender un reclamo?" autoFocus minLength={2} maxLength={1000} /></label><label>Vigencia a consultar<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><label className="checkbox"><input type="checkbox" checked={includeProjects} onChange={(event) => setIncludeProjects(event.target.checked)} /> Incluir proyectos normativos</label><button className="primary" disabled={loading}>{loading ? "Buscando…" : "Consultar RAG"}</button></form>{error && <div className="notice error">{error}</div>}{result ? <div className="rag-results"><div className="result-header"><strong>Resultados para “{result.query}”</strong><span>Vigencia: {result.fecha}{result.fecha_por_defecto ? " (fecha actual)" : ""}</span></div>{result.fragmentos.length ? result.fragmentos.map((fragment, index) => <article className="panel fragment" key={`${fragment.cita.version_id}-${index}`}><span className="result-number">{index + 1}</span><p>{fragment.texto}</p><CitationCard citation={fragment.cita} /></article>) : <Empty>No hay fragmentos para esta consulta y fecha.</Empty>}</div> : <Empty>Escribe una consulta para recuperar la normativa aplicable.</Empty>}</section>;
}

function AlertsPage() {
  const [report, setReport] = useState<Record<string, unknown> | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const load = async () => { setLoading(true); setError(null); try { setReport((await api.report()).reporte); } catch (reason) { setError((reason as Error).message); } finally { setLoading(false); } };
  const entries = useMemo(() => report ? Object.entries(report) : [], [report]);
  return <section className="page"><div className="page-heading"><div><span className="eyebrow">MONITOREO DE OBLIGACIONES</span><h1>Centro de alertas</h1><p>Genera el reporte de cumplimiento y exposición disponible en el módulo compliance.</p></div><button className="primary" onClick={() => void load()} disabled={loading}>{loading ? "Generando…" : "Generar reporte"}</button></div>{error && <div className="notice error">{error}</div>}{report ? <article className="panel report"><div className="panel-title"><h2>Reporte de cumplimiento</h2><Pill value="generado" tone="good" /></div><div className="report-grid">{entries.map(([key, value]) => <div key={key}><span>{stateLabel(key)}</span><strong>{typeof value === "object" ? JSON.stringify(value) : String(value ?? "—")}</strong></div>)}</div></article> : <Empty>El reporte se calcula bajo demanda para reflejar las obligaciones y evidencias vigentes.</Empty>}</section>;
}
