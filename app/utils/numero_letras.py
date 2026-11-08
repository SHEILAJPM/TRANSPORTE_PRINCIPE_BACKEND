"""Importe en letras para la representación impresa de comprobantes ("SON: ...")."""

from decimal import ROUND_HALF_UP, Decimal

_UNIDADES = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE", "DIEZ",
             "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE",
             "VEINTE", "VEINTIUN", "VEINTIDOS", "VEINTITRES", "VEINTICUATRO", "VEINTICINCO", "VEINTISEIS",
             "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
_DECENAS = ["", "", "", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
_CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS",
             "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]


def _menor_a_mil(n: int) -> str:
    if n == 100:
        return "CIEN"
    centena, resto = divmod(n, 100)
    partes = [_CENTENAS[centena]] if centena else []
    if resto < 30:
        partes.append(_UNIDADES[resto])
    else:
        decena, unidad = divmod(resto, 10)
        partes.append(_DECENAS[decena] + (f" Y {_UNIDADES[unidad]}" if unidad else ""))
    return " ".join(p for p in partes if p)


def entero_a_letras(n: int) -> str:
    if n == 0:
        return "CERO"
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1000)
    partes = []
    if millones:
        partes.append("UN MILLON" if millones == 1 else f"{entero_a_letras(millones)} MILLONES")
    if miles:
        partes.append("MIL" if miles == 1 else f"{_menor_a_mil(miles)} MIL")
    if unidades:
        partes.append(_menor_a_mil(unidades))
    return " ".join(partes)


def importe_en_letras(monto, moneda: str = "PEN") -> str:
    """1770.5 -> "MIL SETECIENTOS SETENTA CON 50/100 SOLES"."""
    monto = Decimal(str(monto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    entero = int(monto)
    centimos = int((monto - entero) * 100)
    nombre_moneda = "SOLES" if moneda == "PEN" else "DOLARES AMERICANOS"
    texto = entero_a_letras(entero)
    if texto.endswith("UN"):  # "CIENTO UNO", "VEINTIUNO" (pero "VEINTIUN MIL")
        texto += "O"
    return f"{texto} CON {centimos:02d}/100 {nombre_moneda}"
