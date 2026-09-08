import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ViajeRentabilidadItemResponse(BaseModel):
    id: uuid.UUID
    numero: str
    estado: str
    fecha_salida_programada: datetime
    cliente_razon_social: str
    placa_tracto: str
    placa_carreta: str | None
    origen: str
    destino: str
    ingresos_netos_flete: Decimal
    total_gastos_operativos: Decimal
    monto_dietas_chofer: Decimal
    egresos_totales: Decimal
    ganancia_neta: Decimal

    model_config = {"from_attributes": True}


class ResumenFinancieroResponse(BaseModel):
    """P&L general de la empresa para un rango de fechas: ingresos de todos los
    viajes menos TODOS los egresos (operativos de viaje, dietas, mantenimiento de
    flota y egresos generales de la empresa)."""

    ingresos_totales: Decimal
    egresos_operativos_viajes: Decimal
    dietas_choferes: Decimal
    mantenimiento_flota: Decimal
    egresos_generales: Decimal
    egresos_totales: Decimal
    ganancia_neta: Decimal
