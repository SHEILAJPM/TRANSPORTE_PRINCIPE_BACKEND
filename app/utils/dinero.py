from decimal import ROUND_HALF_UP, Decimal


def a_decimal(valor) -> Decimal:
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def redondear_moneda(valor) -> Decimal:
    return a_decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
