import asyncio

from app.core.database import AsyncSessionLocal
from app.services.alertas_service import listar_alertas_vencimiento
from app.tasks.celery_app import celery_app


async def _revisar_vencimientos_async() -> int:
    async with AsyncSessionLocal() as db:
        alertas = await listar_alertas_vencimiento(db)
        # TODO: enviar por email/WhatsApp/push a los responsables de flota.
        for alerta in alertas:
            print(f"[ALERTA] {alerta.entidad_tipo} {alerta.identificador}: {alerta.concepto} "
                  f"vence {alerta.fecha_vencimiento} (en {alerta.dias_restantes} días)")
        return len(alertas)


@celery_app.task(name="app.tasks.alertas_tasks.revisar_vencimientos")
def revisar_vencimientos() -> int:
    return asyncio.run(_revisar_vencimientos_async())
