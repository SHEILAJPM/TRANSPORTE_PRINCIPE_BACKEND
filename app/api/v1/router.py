from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    choferes,
    clientes,
    comprobantes,
    cotizaciones,
    egresos,
    empresa,
    flota,
    gastos,
    liquidaciones,
    pesos_medidas,
    reportes,
    sunat,
    usuarios,
    viajes,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(usuarios.router)
api_router.include_router(empresa.router)
api_router.include_router(flota.router)
api_router.include_router(choferes.router)
api_router.include_router(clientes.router)
api_router.include_router(sunat.router)
api_router.include_router(cotizaciones.router)
api_router.include_router(viajes.router)
api_router.include_router(gastos.router)
api_router.include_router(comprobantes.router)
api_router.include_router(comprobantes.router_listado)
api_router.include_router(pesos_medidas.router)
api_router.include_router(liquidaciones.router)
api_router.include_router(egresos.router)
api_router.include_router(reportes.router)
