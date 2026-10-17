import { FormEvent, Fragment, ReactNode, useEffect, useMemo, useState } from "react";
import { api, CaseResult, CaseSchema, CaseSummary, Citation, ExpedienteBatchItem, ExpedienteResult, ExpedienteSummary, Health, SearchResult } from "./api";
import { ClampedText, FragmentCard } from "./ResultCards";
import { AgentFlow, ExpedienteFlow, ObligationList } from "./CaseParts";
import ProposalPage from "./Proposal";
import "./import.css";
import "./results.css";
import "./case.css";
import "./proposal.css";

type View = "dashboard" | "cases" | "rag" | "alerts" | "proposal" | "detail" | "expediente-detail";
type Notice = { kind: "error" | "success"; text: string } | null;

const menu: Array<{ id: View; icon: string; label: string }> = [
  { id: "dashboard", icon: "▦", label: "Dashboard principal" },
  { id: "cases", icon: "✓", label: "Gestión de casos" },
  { id: "rag", icon: "⌘", label: "Motor RAG y evaluación IA" },
  { id: "alerts", icon: "◉", label: "Centro de alertas" },
  { id: "proposal", icon: "★", label: "Propuesta" },
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

const formatDate = (iso: string) => iso.split("-").reverse().join("/");

function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export default function App() {
  const [view, setView] = useState<View>("dashboard");
  const [health, setHealth] = useState<Health | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [expedientes, setExpedientes] = useState<ExpedienteSummary[]>([]);
  const [selected, setSelected] = useState<CaseResult | null>(null);
  const [selectedExpediente, setSelectedExpediente] = useState<ExpedienteResult | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    const [healthResult, caseResult, expedienteResult] = await Promise.allSettled([api.health(), api.cases(), api.expedientes()]);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (caseResult.status === "fulfilled") setCases(caseResult.value);
    if (expedienteResult.status === "fulfilled") setExpedientes(expedienteResult.value);
    const failed = [healthResult, caseResult, expedienteResult].find((result) => result.status === "rejected");
    const failure = failed?.status === "rejected" ? failed.reason : null;
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

  const openExpediente = async (id: string) => {
    try {
      setLoading(true);
      setSelectedExpediente(await api.expediente(id));
      setView("expediente-detail");
    } catch (error) { setNotice({ kind: "error", text: (error as Error).message }); }
    finally { setLoading(false); }
  };

  const clearImportedExpedientes = async (count: number) => {
    if (!count || !window.confirm(`Se borrarán ${count} expedientes importados del Registro central. ¿Continuar?`)) return;
    try {
      const { eliminados } = await api.clearExpedientes();
      await refresh();
      setNotice({ kind: "success", text: `Se borraron ${eliminados} expedientes importados. El registro está listo para la demo.` });
    } catch (error) { setNotice({ kind: "error", text: `No se pudieron borrar los expedientes: ${(error as Error).message}` }); }
  };

  const navigate = (next: View) => { setView(next); setNotice(null); };

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">R</div><div><strong>RAG Compliance</strong><small>IA & vigilancia normativa</small></div></div>
      <div className="sidebar-rule" />
      <nav aria-label="Navegación principal">
        {menu.map((item) => <button key={item.id} onClick={() => navigate(item.id)} className={view === item.id || (item.id === "cases" && (view === "detail" || view === "expediente-detail")) ? "nav-item active" : "nav-item"}><span>{item.icon}</span>{item.label}</button>)}
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
        {view === "dashboard" && <Dashboard health={health} cases={cases} expedientes={expedientes} openCase={openCase} go={navigate} />}
        {view === "cases" && <CasesPage cases={cases} expedientes={expedientes} onOpen={openCase} onOpenExpediente={openExpediente} onClearImported={clearImportedExpedientes} onImported={refresh} onCreated={(result) => { setSelected(result); setCases((old) => [{ case_id: result.case.case_id, tipo_evento: result.case.tipo_evento, decision: result.audit_result?.decision ?? null, evaluado_en: result.evaluado_en }, ...old.filter((entry) => entry.case_id !== result.case.case_id)]); setView("detail"); setNotice({ kind: "success", text: "Caso evaluado y registrado correctamente." }); }} />}
        {view === "detail" && <CaseDetail result={selected} onBack={() => setView("cases")} />}
        {view === "expediente-detail" && <ExpedienteDetail result={selectedExpediente} onBack={() => setView("cases")} />}
        {view === "rag" && <RagPage />}
        {view === "alerts" && <AlertsPage />}
        {view === "proposal" && <ProposalPage />}
      </main>
    </div>
  </div>;
}

function Dashboard({ health, cases, expedientes, openCase, go }: { health: Health | null; cases: CaseSummary[]; expedientes: ExpedienteSummary[]; openCase: (id: string) => void; go: (view: View) => void }) {
  const indexed = health?.bases.rag?.versiones_sql ?? 0;
  return <section className="page"><div className="page-heading"><div><span className="eyebrow">PANEL DE CONTROL</span><h1>Inteligencia de cumplimiento</h1><p>Vigilancia regulatoria, evaluación trazable de expedientes y respuestas sustentadas en normativa SBS.</p></div><button className="primary" onClick={() => go("cases")}>+ Evaluar caso</button></div>
    <div className="metrics">
      <Metric label="Estado del backend" value={health ? health.status : "Conectando"} detail={health ? `API v${health.version}` : "Verificando servicios"} tone={health?.status === "ok" ? "good" : "warn"} />
      <Metric label="Versiones RAG indexadas" value={String(indexed)} detail="Base normativa disponible" />
      <Metric label="Registros evaluados" value={String(cases.length + expedientes.length)} detail="Casos individuales e importados" />
      <Metric label="Política de auditoría" value={health?.policy_version ?? "—"} detail={`Modo: ${health?.audit_mode ?? "—"}`} />
    </div>
    <div className="two-col"><article className="panel"><div className="panel-title"><div><h2>Actividad reciente</h2><p>Resultados recuperados desde la API de casos.</p></div><button className="text-button" onClick={() => go("cases")}>Ver todos →</button></div>{cases.length ? <CaseTable cases={cases.slice(0, 6)} onOpen={openCase} /> : <Empty>Aún no hay casos evaluados. Crea el primero desde Gestión de casos.</Empty>}</article>
      <article className="panel"><div className="panel-title"><div><h2>Salud operativa</h2><p>Dependencias del procesamiento local.</p></div></div>{health ? <div className="health-list"><HealthRow label="Ollama" value={health.ollama.reachable ? "Disponible" : "No disponible"} ok={health.ollama.reachable} />{Object.entries(health.ollama.models).map(([model, available]) => <HealthRow key={model} label={model} value={available ? "Cargado" : "Pendiente"} ok={available} />)}<HealthRow label="Cadena de auditoría" value={health.bases.audit ? "Verificada por backend" : "Sin datos"} ok={Boolean(health.bases.audit)} /></div> : <Empty>Esperando respuesta de /health.</Empty>}</article></div>
  </section>;
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: string }) { return <article className="metric"><span>{label}</span><strong className={tone}>{value}</strong><small>{detail}</small></article>; }
function HealthRow({ label, value, ok }: { label: string; value: string; ok: boolean }) { return <div className="health-row"><span><i className={ok ? "online" : "offline"} />{label}</span><Pill value={value} tone={ok ? "good" : "danger"} /></div>; }

function CaseTable({ cases, onOpen }: { cases: CaseSummary[]; onOpen: (id: string) => void }) { return <div className="table-wrap"><table><thead><tr><th>Identificador</th><th>Evento</th><th>Decisión</th><th>Evaluado</th><th /></tr></thead><tbody>{cases.map((item) => <tr key={item.case_id}><td><code>{item.case_id}</code></td><td>{stateLabel(item.tipo_evento)}</td><td><Pill value={item.decision} /></td><td>{new Date(item.evaluado_en).toLocaleDateString("es-PE")}</td><td><button className="row-button" onClick={() => void onOpen(item.case_id)}>Revisar</button></td></tr>)}</tbody></table></div>; }

function ExpedienteTable({ expedientes, onOpen }: { expedientes: ExpedienteSummary[]; onOpen: (id: string) => void }) {
  const labelFor = (result: string) => result === "POSIBLE_INCUMPLIMIENTO" ? "Posible incumplimiento" : result === "SIN_INCUMPLIMIENTO_DETECTADO" ? "Sin indicios detectados" : "Informaci\u00f3n insuficiente";
  const toneFor = (result: string) => result === "POSIBLE_INCUMPLIMIENTO" ? "danger" : result === "SIN_INCUMPLIMIENTO_DETECTADO" ? "good" : "warn";
  return <div className="table-wrap batch-table"><table><thead><tr><th>Identificador</th><th>Resultado</th><th>Auditoría</th><th>Evaluado</th><th /></tr></thead><tbody>{expedientes.map((item) => <tr key={item.id_caso}><td><code>{item.id_caso}</code></td><td><Pill value={labelFor(item.resultado_esperado)} tone={toneFor(item.resultado_esperado)} /></td><td><Pill value={item.decision_auditoria ?? "SIN_AUDITORIA"} /></td><td>{new Date(item.evaluado_en).toLocaleDateString("es-PE")}</td><td><button className="row-button" onClick={() => void onOpen(item.id_caso)}>Revisar</button></td></tr>)}</tbody></table></div>;
}

function CasesPage({ cases, expedientes, onOpen, onOpenExpediente, onClearImported, onCreated, onImported }: { cases: CaseSummary[]; expedientes: ExpedienteSummary[]; onOpen: (id: string) => void; onOpenExpediente: (id: string) => void; onClearImported: (count: number) => void; onCreated: (result: CaseResult) => void; onImported: () => Promise<void> }) {
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [schema, setSchema] = useState<CaseSchema | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [tab, setTab] = useState<"cases" | "expedientes">(cases.length || !expedientes.length ? "cases" : "expedientes");
  const [search, setSearch] = useState(""); const [outcomeFilter, setOutcomeFilter] = useState(""); const [page, setPage] = useState(0);
  const PAGE_SIZE = 15;
  const filtered = useMemo(() => expedientes.filter((item) => (!outcomeFilter || item.resultado_esperado === outcomeFilter) && item.id_caso.toLowerCase().includes(search.trim().toLowerCase())), [expedientes, search, outcomeFilter]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageItems = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);
  useEffect(() => { void api.caseSchema().then(setSchema).catch((reason) => setSchemaError((reason as Error).message)); }, []);
  return <section className="page">
    <div className="page-heading"><div><span className="eyebrow">EXPEDIENTES OFICIALES</span><h1>Gestión integral de casos</h1><p>Registra eventos, evalúa obligaciones y conserva la trazabilidad de la auditoría.</p></div><div className="page-actions"><button className="secondary" onClick={() => setShowImport((visible) => !visible)}>{showImport ? "Cerrar importación" : "Importar CSV"}</button><button className="primary" onClick={() => setShowForm((visible) => !visible)}>{showForm ? "Cerrar formulario" : "+ Nuevo caso"}</button></div></div>
    {schemaError && <div className="notice error">No se pudo cargar el catálogo de eventos: {schemaError}</div>}
    {showImport && <ExpedienteImport onImported={onImported} />}
    {showForm && <CaseForm eventTypes={schema?.tipos_evento ?? {}} onSuccess={onCreated} />}
    <article className="panel">
      <div className="panel-title"><div><h2>Registro central</h2><p>Casos individuales y expedientes importados, por separado.</p></div><div className="registry-actions"><span className="counter">{cases.length + expedientes.length} registros</span><button className="danger-button" type="button" disabled={!expedientes.length} onClick={() => onClearImported(expedientes.length)}>Borrar importados</button></div></div>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "cases"} className={tab === "cases" ? "active" : ""} onClick={() => setTab("cases")}>Casos individuales <span className="counter">{cases.length}</span></button>
        <button type="button" role="tab" aria-selected={tab === "expedientes"} className={tab === "expedientes" ? "active" : ""} onClick={() => setTab("expedientes")}>Expedientes importados <span className="counter">{expedientes.length}</span></button>
      </div>
      <div className="registry-tabs-body">
        {tab === "cases" && (cases.length ? <CaseTable cases={cases} onOpen={onOpen} /> : <Empty>No hay casos individuales. Crea uno con “+ Nuevo caso”.</Empty>)}
        {tab === "expedientes" && (expedientes.length ? <>
          <div className="registry-filters">
            <input type="search" placeholder="Buscar por identificador (ej. SYN-0159)" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0); }} aria-label="Buscar expediente" />
            <select value={outcomeFilter} onChange={(event) => { setOutcomeFilter(event.target.value); setPage(0); }} aria-label="Filtrar por resultado">
              <option value="">Todos los resultados</option>
              <option value="POSIBLE_INCUMPLIMIENTO">Posible incumplimiento</option>
              <option value="INFORMACION_INSUFICIENTE">Información insuficiente</option>
              <option value="SIN_INCUMPLIMIENTO_DETECTADO">Sin indicios detectados</option>
            </select>
            <span className="muted">{filtered.length} de {expedientes.length}</span>
          </div>
          {filtered.length ? <ExpedienteTable expedientes={pageItems} onOpen={onOpenExpediente} /> : <Empty>Ningún expediente coincide con el filtro.</Empty>}
          {pageCount > 1 && <div className="pager"><button type="button" className="secondary small" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>← Anterior</button><span>Página {safePage + 1} de {pageCount}</span><button type="button" className="secondary small" disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)}>Siguiente →</button></div>}
        </> : <Empty>No hay expedientes importados. Usa “Importar CSV”.</Empty>)}
      </div>
    </article>
  </section>;
}

function ExpedienteImport({ onImported }: { onImported: () => Promise<void> }) {
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
      await onImported();
    } catch (reason) {
      setError(`${completed ? `Se procesaron ${completed} casos antes del error. ` : ""}${(reason as Error).message}`);
      if (completed) await onImported();
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

function displayValue(value: unknown): string {
  if (value == null || value === "") return "";
  if (Array.isArray(value)) return value.map(displayValue).filter(Boolean).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function ExpedienteFields({ row, fields }: { row: Record<string, unknown>; fields: Array<[string, string]> }) {
  const values = fields.map(([key, label]) => [label, displayValue(row[key])] as const).filter(([, value]) => value);
  if (!values.length) return <Empty>Este expediente no contiene datos en esta sección.</Empty>;
  return <dl className="data-list">{values.map(([label, value]) => <Fragment key={label}><dt>{label}</dt><dd>{value}</dd></Fragment>)}</dl>;
}

function ExpedienteDetail({ result, onBack }: { result: ExpedienteResult | null; onBack: () => void }) {
  if (!result) return <section className="page"><button className="text-button back" onClick={onBack}>← Volver al registro</button><Empty>Selecciona un expediente importado para consultar su evaluación.</Empty></section>;
  const row = result.fila;
  const outcome = String(row.resultado_esperado ?? "INFORMACION_INSUFICIENTE");
  const label = outcome === "POSIBLE_INCUMPLIMIENTO" ? "Posible incumplimiento" : outcome === "SIN_INCUMPLIMIENTO_DETECTADO" ? "Sin indicios detectados" : "Información insuficiente";
  const tone = outcome === "POSIBLE_INCUMPLIMIENTO" ? "danger" : outcome === "SIN_INCUMPLIMIENTO_DETECTADO" ? "good" : "warn";
  const sections: Array<{ title: string; fields: Array<[string, string]> }> = [
    { title: "Hechos y evidencia", fields: [["hechos_relevantes_del_caso", "Hechos relevantes"], ["evidencia_o_faltantes", "Evidencia y faltantes"], ["cumple_segun_evidencia", "Evaluación según evidencia"], ["por_que_si_o_no", "Fundamento de la evaluación"]] },
    { title: "Norma y fundamento", fields: [["norma_a_consultar", "Norma consultada"], ["razon_de_aplicacion_normativa", "Aplicación al caso"], ["fuente_legal", "Fuente legal"], ["version_id_citada", "Versión citada"], ["sancion_aplicable", "Sanción aplicable"]] },
    { title: "Fechas y alertas internas", fields: [["fecha_registro", "Fecha de registro"], ["fecha_limite_interna", "Fecha límite interna"], ["fecha_atencion", "Fecha de atención"], ["dias_de_retraso_interno", "Días de retraso"], ["explicacion_plazo", "Explicación del plazo"], ["prioridad", "Prioridad"], ["alerta_normativa_esperada", "Alerta normativa"], ["alerta_plazo_interno_esperada", "Alerta de plazo interno"], ["tipo_alerta_esperada", "Tipo de alerta"]] },
    { title: "Auditoría y revisión humana", fields: [["decision_auditoria", "Decisión de auditoría"], ["revision_humana", "Estado de revisión humana"], ["audit_id", "Identificador de auditoría"], ["senales_detectadas", "Señales detectadas"], ["reglas_version", "Versión de reglas"], ["modalidad_analisis", "Modalidad de análisis"], ["fuente_patron", "Fuente del patrón"], ["limitacion_de_la_evaluacion", "Limitaciones"]] },
  ];
  return <section className="page"><button className="text-button back" onClick={onBack}>← Gestión de casos</button><div className="page-heading compact"><div><span className="eyebrow">EXPEDIENTE IMPORTADO</span><h1>{displayValue(row.id_caso) || "Sin identificador"}</h1><p>Resultado de revisión del CSV con evidencia, norma y trazabilidad.</p></div><div className="decision"><Pill value={label} tone={tone} /><Pill value={displayValue(row.decision_auditoria) || "SIN_AUDITORIA"} /><small>La clasificación requiere revisión humana.</small></div></div>
    <div className="detail-grid"><article className="panel highlight"><div className="panel-title"><h2>Conclusión</h2><Pill value={displayValue(row.revision_humana) || "PENDIENTE_REVISION"} /></div><p className="summary">{displayValue(row.por_que_si_o_no) || "No se guardó una explicación para este resultado."}</p>{displayValue(row.limitacion_de_la_evaluacion) && <p className="case-description">Limitación: {displayValue(row.limitacion_de_la_evaluacion)}</p>}</article><article className="panel"><div className="panel-title"><h2>Identificación</h2></div><ExpedienteFields row={row} fields={[["id_caso", "ID del expediente"], ["resultado_esperado", "Resultado"], ["prioridad", "Prioridad"], ["revision_humana", "Revisión humana"]]} /></article></div>
    <ExpedienteFlow result={result} />
    <div className="two-col wide-left">{sections.map((section) => <article className="panel" key={section.title}><div className="panel-title"><h2>{section.title}</h2></div><ExpedienteFields row={row} fields={section.fields} /></article>)}</div>
  </section>;
}

function CaseDetail({ result, onBack }: { result: CaseResult | null; onBack: () => void }) {
  if (!result) return <section className="page"><button className="text-button" onClick={onBack}>← Volver a casos</button><Empty>Selecciona un caso del registro para consultar su dictamen.</Empty></section>;
  const decision = result.audit_result?.decision ?? (result.publicable ? "publicable" : "pendiente");
  return <section className="page"><button className="text-button back" onClick={onBack}>← Gestión de casos</button><div className="page-heading compact"><div><span className="eyebrow">DICTAMEN Y TRAZABILIDAD</span><h1>{result.case.case_id}</h1><p>{result.evento_descripcion}</p></div><div className="decision"><Pill value={decision} /><small>Evaluado: {new Date(result.evaluado_en).toLocaleString("es-PE")}</small></div></div>
    <div className="detail-grid"><article className="panel"><div className="panel-title"><h2>Información del caso</h2></div><dl className="data-list"><dt>Responsable</dt><dd>{result.case.user_id} · {stateLabel(result.case.rol)}</dd><dt>Evento</dt><dd>{stateLabel(result.case.tipo_evento)}</dd><dt>Fecha</dt><dd>{result.case.fecha_evento}</dd><dt>Monto</dt><dd>{result.case.monto != null ? `${result.case.moneda} ${result.case.monto.toLocaleString("es-PE")}` : "No declarado"}</dd></dl><ClampedText className="case-description" text={result.case.descripcion || "Sin descripción adicional."} lines={4} /></article><article className="panel highlight"><div className="panel-title"><h2>Conclusión asistida</h2><Pill value={result.resumen_origen} tone="neutral" /></div><ClampedText className="summary" text={result.resumen} lines={5} />{result.advertencias.length > 0 && <ul className="warnings">{result.advertencias.map((warning) => <li key={warning}>{warning}</li>)}</ul>}</article></div>
    <AgentFlow result={result} />
    <div className="two-col wide-left"><article className="panel"><div className="panel-title"><div><h2>Obligaciones y fundamento</h2><p>Hallazgos obtenidos desde normas indexadas.</p></div></div>{result.obligaciones.length ? <ObligationList items={result.obligaciones} /> : <Empty>No se encontraron obligaciones validadas para este caso.</Empty>}</article><article className="panel"><div className="panel-title"><h2>Plazos y exposición</h2></div>{result.plazos.map((item) => <div className="deadline" key={`${item.obligacion_codigo}-${item.estado}`}><div><strong>{item.obligacion_codigo}</strong><small>{item.detalle || "Sin detalle"}</small></div><Pill value={item.estado} /></div>)}{result.exposicion.map((item) => <div className="exposure" key={`${item.obligacion_codigo}-${item.descripcion}`}><Pill value={item.gravedad ?? "sin gravedad"} /><strong>{item.descripcion}</strong><small>{item.infraccion_numeral ?? "Sin numeral"} · {formatMoney(item.max_soles)} máximo potencial</small></div>)}{!result.plazos.length && !result.exposicion.length && <Empty>Sin plazos ni exposición aplicable.</Empty>}</article></div>
  </section>;
}

function RagPage() {
  const [query, setQuery] = useState(""); const [date, setDate] = useState(""); const [includeProjects, setIncludeProjects] = useState(false); const [result, setResult] = useState<SearchResult | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false); const [openSet, setOpenSet] = useState<Set<number>>(new Set([0]));
  const toggleFragment = (index: number) => setOpenSet((prev) => { const next = new Set(prev); if (next.has(index)) next.delete(index); else next.add(index); return next; });
  const submit = async (event: FormEvent) => { event.preventDefault(); if (query.trim().length < 2) return; setLoading(true); setError(null); try { setResult(await api.search({ query: query.trim(), fecha: date || undefined, top_k: 5, incluir_proyectos: includeProjects })); setOpenSet(new Set([0])); } catch (reason) { setError((reason as Error).message); } finally { setLoading(false); } };
  return <section className="page"><div className="page-heading"><div><span className="eyebrow">BASE NORMATIVA SBS</span><h1>Motor RAG y evaluación IA</h1><p>Consulta normativa con fecha de vigencia y citas de la versión aplicable.</p></div></div><form className="search-panel search-panel-wide panel" onSubmit={submit}><label className="search-label">Pregunta normativa<textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="¿Cuál es el plazo para atender un reclamo? Puedes pegar la descripción completa de un caso." autoFocus minLength={2} maxLength={1000} rows={3} onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) event.currentTarget.form?.requestSubmit(); }} /></label><label className="date-label">Vigencia a consultar<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><label className="checkbox"><input type="checkbox" checked={includeProjects} onChange={(event) => setIncludeProjects(event.target.checked)} /> Incluir proyectos normativos</label><button className="primary" disabled={loading}>{loading ? "Buscando…" : "Consultar RAG"}</button></form>{error && <div className="notice error">{error}</div>}{result ? <div className="rag-results"><div className="rag-summary"><div className="rag-summary-top"><div className="chips"><span className="chip chip-strong">{result.fragmentos.length} {result.fragmentos.length === 1 ? "fragmento" : "fragmentos"}</span><span className="chip">Vigencia: {formatDate(result.fecha)}{result.fecha_por_defecto ? " (fecha actual)" : ""}</span></div>{result.fragmentos.length > 1 && <div className="rag-tools"><button type="button" className="secondary" onClick={() => setOpenSet(new Set(result.fragmentos.map((_, i) => i)))}>Expandir todo</button><button type="button" className="secondary" onClick={() => setOpenSet(new Set())}>Contraer todo</button></div>}</div><div className="rag-query"><span className="label">CONSULTA</span><ClampedText text={result.query} lines={2} /></div></div>{result.fragmentos.length ? result.fragmentos.map((fragment, index) => <FragmentCard key={`${fragment.cita.version_id}-${index}`} index={index} texto={fragment.texto} cita={fragment.cita} open={openSet.has(index)} onToggle={() => toggleFragment(index)} />) : <Empty>No hay fragmentos para esta consulta y fecha.</Empty>}</div> : <Empty>Escribe una consulta para recuperar la normativa aplicable.</Empty>}</section>;
}

function AlertsPage() {
  const [report, setReport] = useState<Record<string, unknown> | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const load = async () => { setLoading(true); setError(null); try { setReport((await api.report()).reporte); } catch (reason) { setError((reason as Error).message); } finally { setLoading(false); } };
  const entries = useMemo(() => report ? Object.entries(report) : [], [report]);
  return <section className="page"><div className="page-heading"><div><span className="eyebrow">MONITOREO DE OBLIGACIONES</span><h1>Centro de alertas</h1><p>Genera el reporte de cumplimiento y exposición disponible en el módulo compliance.</p></div><button className="primary" onClick={() => void load()} disabled={loading}>{loading ? "Generando…" : "Generar reporte"}</button></div>{error && <div className="notice error">{error}</div>}{report ? <article className="panel report"><div className="panel-title"><h2>Reporte de cumplimiento</h2><Pill value="generado" tone="good" /></div><div className="report-grid">{entries.map(([key, value]) => <div key={key}><span>{stateLabel(key)}</span><strong>{typeof value === "object" ? JSON.stringify(value) : String(value ?? "—")}</strong></div>)}</div></article> : <Empty>El reporte se calcula bajo demanda para reflejar las obligaciones y evidencias vigentes.</Empty>}</section>;
}
