import { ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const reducedMotion = () => {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
};

/** Número que sube hasta su valor (respeta prefers-reduced-motion). */
export function CountUp({ value, duration = 700, decimals = 0 }: { value: number; duration?: number; decimals?: number }) {
  const [shown, setShown] = useState(reducedMotion() ? value : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reducedMotion()) { setShown(value); return; }
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(origin + (value - origin) * eased);
      if (p < 1) frame = requestAnimationFrame(tick); else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(frame); from.current = value; };
  }, [value, duration]);
  return <>{shown.toLocaleString("es-PE", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</>;
}

export function Skeleton({ h = 16, w = "100%", r = 8 }: { h?: number; w?: number | string; r?: number }) {
  return <span className="skeleton" style={{ height: h, width: w, borderRadius: r }} aria-hidden />;
}

/** Diálogo modal accesible: Esc y clic fuera cierran, foco en el primer campo.
    Va en un portal sobre <body> para que ninguna vista animada lo recorte. */
export function Modal({ title, subtitle, onClose, children, footer }: { title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode; footer: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  // Solo al montar: si dependiera de onClose (nueva en cada render) el foco saltaria al escribir.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const first = box.current?.querySelector<HTMLElement>("input, textarea, select") ?? box.current?.querySelector<HTMLElement>(".modal-foot button");
    first?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close.current(); };
    document.addEventListener("keydown", onKey);
    document.body.classList.add("modal-open");
    return () => { document.removeEventListener("keydown", onKey); document.body.classList.remove("modal-open"); previous?.focus?.(); };
  }, []);
  return createPortal(<div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" ref={box}>
      <div className="modal-head"><div><h2 id="modal-title">{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button type="button" className="modal-x" aria-label="Cerrar" onClick={onClose}>×</button></div>
      <div className="modal-body">{children}</div>
      <div className="modal-foot">{footer}</div>
    </div>
  </div>, document.body);
}
