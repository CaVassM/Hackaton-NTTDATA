"""Motor de plazos: obligacion validada + evidencia interna -> estado por caso.

  fecha_limite = fecha_evento + plazo
  dias_atraso  = max(0, (fecha_cumplimiento o fecha_corte) - fecha_limite)
  estado: cumplido | atrasado | por_vencer | sin_plazo_definido | sin_evidencia
"""
import re
from collections.abc import Sequence
from datetime import date

from modules.compliance.deadlines.calendar import sumar_plazo
from modules.compliance.domain import EstadoPlazo, EvidenciaInterna, Obligacion, ResultadoPlazo

# Periodicidad sin numero ("dos capacitaciones AL AÑO"): el periodo es 1 unidad
# SOLO si la propia cita lo dice con estas palabras. Si no, sin plazo definido.
_PERIODO_IMPLICITO = {
    "anios": re.compile(r"(?i)\bal año\b|\banual(es|mente)?\b|\bcada año\b"),
    "meses": re.compile(r"(?i)\bal mes\b|\bmensual(es|mente)?\b|\bcada mes\b"),
}


def plazo_de(o: Obligacion) -> tuple[int, str, str | None, str] | None:
    """(valor, unidad, tipo, nota) o None si la obligacion no define plazo computable."""
    if o.plazo_unidad is None:
        return None
    if o.plazo_valor is not None:
        return o.plazo_valor, o.plazo_unidad, o.tipo_plazo, ""
    rx = _PERIODO_IMPLICITO.get(o.plazo_unidad)
    if o.tipo_plazo == "periodico" and rx and rx.search(o.cita_textual):
        return 1, o.plazo_unidad, "periodico", f"periodo de 1 {o.plazo_unidad} leido de la cita ('{rx.search(o.cita_textual).group(0)}')"
    return None


class DeadlineEngine:
    def __init__(self, feriados: set[date] | None = None):
        self.feriados = feriados or set()

    def evaluar(self, o: Obligacion, evidencias: Sequence[EvidenciaInterna], fecha_corte: date | None) -> list[ResultadoPlazo]:
        if not evidencias:
            return [ResultadoPlazo(o.codigo, None, EstadoPlazo.SIN_EVIDENCIA,
                                   detalle="No hay evidencia interna para esta obligacion")]
        plazo = plazo_de(o)
        return [self._caso(o, ev, plazo, fecha_corte) for ev in evidencias]

    def _caso(self, o: Obligacion, ev: EvidenciaInterna, plazo, fecha_corte: date | None) -> ResultadoPlazo:
        base = {"obligacion_codigo": o.codigo, "sujeto_id": ev.sujeto_id, "fecha_evento": ev.fecha_evento}
        if plazo is None:
            return ResultadoPlazo(**base, estado=EstadoPlazo.SIN_PLAZO_DEFINIDO,
                                  detalle=f"La obligacion no fija un plazo computable ({o.plazo_texto or 'sin plazo'})")
        valor, unidad, tipo, nota = plazo
        corte = fecha_corte or ev.fecha_corte  # la fecha del reporte manda sobre la del CSV
        if corte is None:
            return ResultadoPlazo(**base, estado=EstadoPlazo.SIN_EVIDENCIA, detalle="Falta fecha_corte (reporte o CSV)")
        limite = sumar_plazo(ev.fecha_evento, valor, unidad, tipo, self.feriados)
        tipo_txt = "habiles" if tipo == "habil" else ("periodico" if tipo == "periodico" else "calendario")
        regla = f"{valor} {unidad} ({tipo_txt}) desde {ev.fecha_evento}" + (f"; {nota}" if nota else "")

        if ev.fecha_cumplimiento is not None and ev.fecha_cumplimiento <= corte:
            atraso = max(0, (ev.fecha_cumplimiento - limite).days)
            estado = EstadoPlazo.CUMPLIDO if atraso == 0 else EstadoPlazo.ATRASADO
            detalle = "Cumplido en plazo" if atraso == 0 else f"Cumplido fuera de plazo ({atraso} dias tarde)"
            return ResultadoPlazo(**base, estado=estado, fecha_limite=limite, fecha_referencia=ev.fecha_cumplimiento,
                                  dias_atraso=atraso, detalle=f"{detalle}. Regla: {regla}")

        # Sin cumplimiento a la fecha de corte.
        if corte > limite:
            atraso = (corte - limite).days
            return ResultadoPlazo(**base, estado=EstadoPlazo.ATRASADO, fecha_limite=limite, fecha_referencia=corte,
                                  dias_atraso=atraso, detalle=f"Pendiente y vencido hace {atraso} dias. Regla: {regla}")
        faltan = (limite - corte).days
        return ResultadoPlazo(**base, estado=EstadoPlazo.POR_VENCER, fecha_limite=limite, fecha_referencia=corte,
                              dias_para_vencer=faltan, detalle=f"Pendiente; vence en {faltan} dias. Regla: {regla}")
