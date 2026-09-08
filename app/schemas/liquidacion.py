from decimal import Decimal

from pydantic import BaseModel


class LiquidacionResponse(BaseModel):
    dias_viaje: int
    noches_viaje: int
    tarifa_diaria: Decimal
    bono_nocturno: Decimal
    monto_dietas: Decimal
    total_adelantos_recibidos: Decimal
    total_gastos_operativos: Decimal
    saldo_rendicion_cuentas: Decimal
    neto_a_pagar_chofer: Decimal
    estado: str

    model_config = {"from_attributes": True}


class RentabilidadResponse(BaseModel):
    ingresos_netos_flete: Decimal
    total_gastos_operativos: Decimal
    monto_dietas_chofer: Decimal
    egresos_totales: Decimal
    ganancia_neta: Decimal
