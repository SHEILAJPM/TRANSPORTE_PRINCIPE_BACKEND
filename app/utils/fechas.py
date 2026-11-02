from datetime import datetime, timedelta, timezone

# Perú no tiene horario de verano: UTC-5 fijo (evita depender de tzdata en Windows).
ZONA_PERU = timezone(timedelta(hours=-5), "America/Lima")


def ahora_peru() -> datetime:
    """Fecha y hora oficiales para los comprobantes: SUNAT rechaza una fecha de
    emisión futura, que es lo que daría usar UTC después de las 7 p. m. en Lima."""
    return datetime.now(ZONA_PERU)


def en_hora_peru(momento: datetime) -> datetime:
    """Convierte una fecha-hora con zona a la hora de Perú. Una sin zona se asume ya
    en hora de Perú (así la ingresa el usuario en los formularios)."""
    if momento.tzinfo is None:
        return momento.replace(tzinfo=ZONA_PERU)
    return momento.astimezone(ZONA_PERU)
