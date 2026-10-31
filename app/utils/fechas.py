from datetime import datetime, timedelta, timezone

# Perú no tiene horario de verano: UTC-5 fijo (evita depender de tzdata en Windows).
ZONA_PERU = timezone(timedelta(hours=-5), "America/Lima")


def ahora_peru() -> datetime:
    """Fecha y hora oficiales para los comprobantes: SUNAT rechaza una fecha de
    emisión futura, que es lo que daría usar UTC después de las 7 p. m. en Lima."""
    return datetime.now(ZONA_PERU)
