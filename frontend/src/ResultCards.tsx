import { useLayoutEffect, useRef, useState } from "react";
import type { Citation } from "./api";

/** Texto largo con vista previa de N líneas y botón "Ver más / Ver menos" (solo si realmente se corta). */
export function ClampedText({ text, lines = 3, className = "" }: { text: string; lines?: number; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && !open) setOverflows(el.scrollHeight > el.clientHeight + 1);
  }, [text, lines, open]);
  return <div className={`clamped ${className}`}>
    <p ref={ref} className={open ? "" : "is-clamped"} style={open ? undefined : { WebkitLineClamp: lines }}>{text}</p>
    {(overflows || open) && <button type="button" className="text-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Ver menos" : "Ver más"}<span className={`chev ${open ? "up" : ""}`} aria-hidden>▾</span></button>}
  </div>;
}

/** Primera línea corta = título del artículo; el resto = cuerpo. */
function splitFragment(texto: string): { title: string | null; body: string } {
  const clean = texto.replace(/\r/g, "").trim();
  const [first, ...rest] = clean.split("\n");
  if (rest.length && first.trim().length <= 160) return { title: first.trim(), body: rest.join("\n").trim() };
  return { title: null, body: clean };
}

const formatDate = (iso?: string | null) => iso ? iso.split("-").reverse().join("/") : "";

export function FragmentCard({ index, texto, cita, open, onToggle }: { index: number; texto: string; cita: Citation; open: boolean; onToggle: () => void }) {
  const { title, body } = splitFragment(texto);
  const id = `fragment-${index}-${cita.version_id}`;
  return <article className={`fragment-card panel ${open ? "is-open" : ""}`}>
    <button type="button" className="fragment-head" aria-expanded={open} aria-controls={id} onClick={onToggle}>
      <span className="result-badge">{index + 1}</span>
      <span className="fragment-heading">
        <strong>{title ?? `${cita.norma} · Art. ${cita.articulo}`}</strong>
        <span className="chips">
          <span className="chip chip-strong">{cita.norma}</span>
          <span className="chip">Art. {cita.articulo}</span>
          <span className="chip">Versión {cita.version_id}</span>
          <span className="chip">Desde {formatDate(cita.vigente_desde)}{cita.vigente_hasta ? ` hasta ${formatDate(cita.vigente_hasta)}` : ""}</span>
          {cita.fue_modificada && <span className="chip chip-warn">Modificada{cita.version_vigente_actual_id ? ` · vigente: v${cita.version_vigente_actual_id}` : ""}</span>}
        </span>
      </span>
      <span className={`chev big ${open ? "up" : ""}`} aria-hidden>▾</span>
    </button>
    <div id={id} className="fragment-body">
      {open ? <div className="fragment-text">{body}</div> : <p className="fragment-preview">{body}</p>}
      {!open && <button type="button" className="text-toggle" onClick={onToggle}>Ver texto completo<span className="chev" aria-hidden>▾</span></button>}
    </div>
  </article>;
}
