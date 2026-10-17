const API_URL = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");

export type Citation = {
  norma: string;
  articulo: string;
  version_id: number;
  vigente_desde: string;
  vigente_hasta: string | null;
  fue_modificada?: boolean;
  version_vigente_actual_id?: number | null;
  score?: number;
};

export type CaseSummary = { case_id: string; tipo_evento: string; decision: string | null; evaluado_en: string };
export type ExpedienteSummary = { id_caso: string; resultado_esperado: string; decision_auditoria: string | null; evaluado_en: string };
export type ExpedienteResult = { fila: Record<string, unknown>; audit_result?: Record<string, unknown> | null; auditoria_error?: string | null; tiempos_ms?: Record<string, number> };
export type CaseSchema = {
  tipos_evento: Record<string, { categoria: string; descripcion: string; fecha_evento_significa: string; obligaciones: string[] }>;
};
export type CaseResult = {
  case: { case_id: string; user_id: string; rol: string; tipo_evento: string; fecha_evento: string; fecha_cumplimiento?: string | null; monto?: number | null; moneda: string; descripcion?: string | null };
  categoria: string;
  evento_descripcion: string;
  obligaciones: Array<{ codigo: string; estado_validacion: string; sujeto?: string | null; accion_requerida?: string | null; plazo_texto?: string | null; cita_textual?: string | null; cita?: Citation | null }>;
  plazos: Array<{ obligacion_codigo: string; estado: string; fecha_limite?: string | null; dias_atraso: number; dias_para_vencer?: number | null; detalle: string }>;
  exposicion: Array<{ obligacion_codigo: string; infraccion_numeral?: string | null; gravedad?: string | null; descripcion: string; multa_min_uit?: number | null; multa_max_uit?: number | null; min_soles?: number | null; max_soles?: number | null; nota: string }>;
  resumen: string;
  resumen_origen: string;
  publicable: boolean;
  sin_fundamento: boolean;
  advertencias: string[];
  claims?: Array<{ claim_id: string; text: string; type: string }>;
  claims_rechazados?: Array<Record<string, unknown>>;
  audit_result?: { decision?: string; audit_id?: string; razones?: string[]; score?: number; risk_level?: string; policy_version?: string; findings?: Array<{ validator: string; status: string; critical?: boolean; reason: string }> } | null;
  auditoria_error?: string | null;
  tiempos_ms: Record<string, number>;
  evaluado_en: string;
};

export type ExpedienteBatchItem = {
  id_caso: string | null;
  ok: boolean;
  error?: string | null;
  result?: { fila: Record<string, unknown> } | null;
};

export type SearchResult = { query: string; fecha: string; fecha_por_defecto: boolean; fragmentos: Array<{ texto: string; cita: Citation }> };
export type Health = { status: "ok" | "degradado"; version: string; ollama: { reachable: boolean; models: Record<string, boolean>; error?: string | null }; bases: { rag?: { versiones_sql?: number; [key: string]: unknown }; cases?: Record<string, unknown>; [key: string]: unknown }; audit_mode: string; policy_version: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { headers: { "Content-Type": "application/json", ...init?.headers }, ...init });
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try { const body = await response.json(); detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body); } catch { /* respuesta sin JSON */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

async function uploadCsv<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_URL}${path}`, { method: "POST", body: form });
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try { const body = await response.json(); detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body); } catch { /* respuesta sin JSON */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  cases: () => request<CaseSummary[]>("/cases"),
  expedientes: () => request<ExpedienteSummary[]>("/cases/expedientes?limit=1000"),
  expediente: (id: string) => request<ExpedienteResult>(`/cases/expedientes/${encodeURIComponent(id)}`),
  clearExpedientes: () => request<{ eliminados: number }>("/cases/expedientes?confirmar=true", { method: "DELETE" }),
  caseSchema: () => request<CaseSchema>("/cases/schema"),
  case: (id: string) => request<CaseResult>(`/cases/${encodeURIComponent(id)}`),
  evaluateCase: (payload: unknown) => request<CaseResult>("/cases/evaluate", { method: "POST", body: JSON.stringify(payload) }),
  importExpedientesCsv: (file: File) => uploadCsv<ExpedienteBatchItem[]>("/cases/expedientes/batch?formato=json", file),
  search: (payload: { query: string; fecha?: string; top_k: number; incluir_proyectos: boolean }) => request<SearchResult>("/rag/search", { method: "POST", body: JSON.stringify(payload) }),
  report: () => request<{ reporte: Record<string, unknown> }>("/compliance/report", { method: "POST", body: JSON.stringify({}) }),
};
