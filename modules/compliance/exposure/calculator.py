"""Exposicion potencial. Monto SOLO si la infraccion (validada) tiene multa en
su cita; si no, "monto no determinado". Siempre rotulado como exposicion
potencial, no sancion determinada."""
from modules.compliance.domain import MONTO_NO_DETERMINADO, Exposicion, Infraccion


class ExposureCalculator:
    def __init__(self, uit_valor: float | None):
        if uit_valor is not None and uit_valor <= 0:
            raise ValueError("UIT_VALOR debe ser positivo")
        self.uit_valor = uit_valor

    def calcular(self, inf: Infraccion) -> Exposicion:
        mn, mx = inf.multa_min_uit, inf.multa_max_uit
        if mn is None and mx is None:
            return Exposicion(inf.id, inf.gravedad, None, None, None, None, False,
                              f"{MONTO_NO_DETERMINADO}: la cita de la infraccion no fija multa en UIT")
        if self.uit_valor is None:
            return Exposicion(inf.id, inf.gravedad, mn, mx, None, None, True,
                              "UIT_VALOR no configurado en .env: solo se reporta el rango en UIT")
        a_soles = lambda v: round(v * self.uit_valor, 2) if v is not None else None  # noqa: E731
        nota = "rango 'hasta': sin minimo explicito en la cita" if mn is None else "rango tomado de la cita"
        return Exposicion(inf.id, inf.gravedad, mn, mx, a_soles(mn), a_soles(mx), True,
                          f"{nota}; UIT = S/ {self.uit_valor:,.2f}")
