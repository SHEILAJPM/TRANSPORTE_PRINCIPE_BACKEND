from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chofer import Chofer
from app.models.flota import Carreta, Tracto


@dataclass(frozen=True)
class AlertaVencimiento:
    entidad_tipo: str  # TRACTO | CARRETA | CHOFER
    entidad_id: str
    identificador: str  # placa o nombre del chofer
    concepto: str  # SOAT | CITV | HABILITACION_MTC | LICENCIA | EXAMEN_MEDICO
    fecha_vencimiento: date
    dias_restantes: int

    @property
    def vencido(self) -> bool:
        return self.dias_restantes < 0


def _evaluar(entidad_tipo: str, entidad_id, identificador: str, concepto: str, vencimiento: date | None, dias_anticipacion: int, hoy: date) -> AlertaVencimiento | None:
    if vencimiento is None:
        return None
    dias_restantes = (vencimiento - hoy).days
    if dias_restantes <= dias_anticipacion:
        return AlertaVencimiento(
            entidad_tipo=entidad_tipo,
            entidad_id=str(entidad_id),
            identificador=identificador,
            concepto=concepto,
            fecha_vencimiento=vencimiento,
            dias_restantes=dias_restantes,
        )
    return None


async def listar_alertas_vencimiento(db: AsyncSession) -> list[AlertaVencimiento]:
    """Vehículos (SOAT/CITV/Habilitación MTC) y choferes (licencia/examen médico)
    vencidos o próximos a vencer, según los umbrales configurados en Settings.
    """
    hoy = date.today()
    alertas: list[AlertaVencimiento] = []

    tractos = (await db.execute(select(Tracto))).scalars().all()
    for t in tractos:
        for concepto, vencimiento, dias in (
            ("SOAT", t.soat_vencimiento, settings.ALERTA_DIAS_ANTICIPACION_SOAT),
            ("CITV", t.citv_vencimiento, settings.ALERTA_DIAS_ANTICIPACION_CITV),
            ("HABILITACION_MTC", t.mtc_habilitacion_vencimiento, settings.ALERTA_DIAS_ANTICIPACION_MTC),
        ):
            alerta = _evaluar("TRACTO", t.id, t.placa, concepto, vencimiento, dias, hoy)
            if alerta:
                alertas.append(alerta)

    carretas = (await db.execute(select(Carreta))).scalars().all()
    for c in carretas:
        for concepto, vencimiento, dias in (
            ("SOAT", c.soat_vencimiento, settings.ALERTA_DIAS_ANTICIPACION_SOAT),
            ("CITV", c.citv_vencimiento, settings.ALERTA_DIAS_ANTICIPACION_CITV),
            ("HABILITACION_MTC", c.mtc_habilitacion_vencimiento, settings.ALERTA_DIAS_ANTICIPACION_MTC),
        ):
            alerta = _evaluar("CARRETA", c.id, c.placa, concepto, vencimiento, dias, hoy)
            if alerta:
                alertas.append(alerta)

    choferes = (await db.execute(select(Chofer).where(Chofer.activo.is_(True)))).scalars().all()
    for ch in choferes:
        nombre = f"{ch.nombres} {ch.apellidos}"
        for concepto, vencimiento, dias in (
            ("LICENCIA", ch.licencia_vencimiento, settings.ALERTA_DIAS_ANTICIPACION_LICENCIA),
            ("EXAMEN_MEDICO", ch.examen_medico_vencimiento, settings.ALERTA_DIAS_ANTICIPACION_LICENCIA),
        ):
            alerta = _evaluar("CHOFER", ch.id, nombre, concepto, vencimiento, dias, hoy)
            if alerta:
                alertas.append(alerta)

    return sorted(alertas, key=lambda a: a.dias_restantes)
