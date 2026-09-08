import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EstadoLiquidacion, TipoGastoViaje
from app.models.gasto_viaje import GastoViaje
from app.models.liquidacion import LiquidacionChofer
from app.models.viaje import Viaje
from app.utils.dinero import a_decimal, redondear_moneda

# Tipos de gasto que representan salida real de dinero (rendibles); ADELANTO es
# el ingreso de efectivo en manos del chofer, no un gasto en sí mismo.
TIPOS_GASTO_OPERATIVO = (TipoGastoViaje.COMBUSTIBLE, TipoGastoViaje.PEAJE, TipoGastoViaje.VIATICO, TipoGastoViaje.OTRO)


class ViajeSinFechasError(Exception):
    pass


def calcular_dias_noches(fecha_salida: datetime, fecha_llegada: datetime) -> tuple[int, int]:
    """Días = bloques de 24h del viaje, redondeados hacia arriba (mínimo 1).
    Noches = una por cada día completo fuera de base (dias - 1, mínimo 0).
    """
    if fecha_llegada <= fecha_salida:
        raise ViajeSinFechasError("La fecha de llegada debe ser posterior a la fecha de salida")

    horas_totales = (fecha_llegada - fecha_salida).total_seconds() / 3600
    dias = max(1, math.ceil(horas_totales / 24))
    noches = max(0, dias - 1)
    return dias, noches


@dataclass(frozen=True)
class ResultadoLiquidacion:
    dias_viaje: int
    noches_viaje: int
    tarifa_diaria: Decimal
    bono_nocturno: Decimal
    monto_dietas: Decimal
    total_adelantos_recibidos: Decimal
    total_gastos_operativos: Decimal
    saldo_rendicion_cuentas: Decimal
    neto_a_pagar_chofer: Decimal


def calcular_liquidacion(
    dias_viaje: int,
    noches_viaje: int,
    tarifa_diaria,
    bono_nocturno,
    total_adelantos_recibidos,
    total_gastos_operativos,
) -> ResultadoLiquidacion:
    """Lógica matemática exacta del pago al chofer.

    1) DIETAS — lo que el chofer GANA por el viaje (dietas + nocturnidad):
         monto_dietas = (dias_viaje x tarifa_diaria) + (noches_viaje x bono_nocturno)

    2) RENDICIÓN DE CUENTAS — el efectivo adelantado es dinero de la empresa que el
       chofer usa para pagar combustible/peajes/viáticos en ruta; al cierre se
       compara contra lo realmente gastado (con sustento: tickets/boletas):
         saldo_rendicion_cuentas = total_adelantos_recibidos - total_gastos_operativos
           > 0  el chofer se quedó con efectivo de la empresa que debe devolver.
           < 0  el chofer puso de su bolsillo más de lo que se le adelantó.

    3) NETO A PAGAR AL CHOFER — su ingreso (dietas) neteado contra el efectivo de
       la empresa que aún conserva (o que la empresa le debe si gastó de más):
         neto_a_pagar_chofer = monto_dietas - saldo_rendicion_cuentas
    """
    tarifa_diaria = a_decimal(tarifa_diaria)
    bono_nocturno = a_decimal(bono_nocturno)

    monto_dietas = redondear_moneda(Decimal(dias_viaje) * tarifa_diaria + Decimal(noches_viaje) * bono_nocturno)
    adelantos = redondear_moneda(total_adelantos_recibidos)
    gastos_operativos = redondear_moneda(total_gastos_operativos)
    saldo_rendicion_cuentas = redondear_moneda(adelantos - gastos_operativos)
    neto_a_pagar_chofer = redondear_moneda(monto_dietas - saldo_rendicion_cuentas)

    return ResultadoLiquidacion(
        dias_viaje=dias_viaje,
        noches_viaje=noches_viaje,
        tarifa_diaria=tarifa_diaria,
        bono_nocturno=bono_nocturno,
        monto_dietas=monto_dietas,
        total_adelantos_recibidos=adelantos,
        total_gastos_operativos=gastos_operativos,
        saldo_rendicion_cuentas=saldo_rendicion_cuentas,
        neto_a_pagar_chofer=neto_a_pagar_chofer,
    )


async def sumar_gastos_por_tipo(db: AsyncSession, viaje_id: uuid.UUID, tipos: tuple[TipoGastoViaje, ...]) -> Decimal:
    stmt = select(func.coalesce(func.sum(GastoViaje.monto), 0)).where(
        GastoViaje.viaje_id == viaje_id, GastoViaje.tipo_gasto.in_(tipos)
    )
    total = (await db.execute(stmt)).scalar_one()
    return a_decimal(total)


async def generar_liquidacion_viaje(db: AsyncSession, viaje_id: uuid.UUID) -> LiquidacionChofer:
    """Calcula (o recalcula) la liquidación de un viaje a partir de sus gastos
    registrados y persiste/actualiza el registro LiquidacionChofer asociado.
    """
    viaje = await db.get(Viaje, viaje_id)
    if viaje is None:
        raise ValueError("Viaje no encontrado")

    if viaje.fecha_salida_real and viaje.fecha_llegada_real:
        dias, noches = calcular_dias_noches(viaje.fecha_salida_real, viaje.fecha_llegada_real)
    else:
        dias, noches = viaje.dias_viaje, viaje.noches_viaje

    total_adelantos = await sumar_gastos_por_tipo(db, viaje_id, (TipoGastoViaje.ADELANTO,))
    total_gastos_operativos = await sumar_gastos_por_tipo(db, viaje_id, TIPOS_GASTO_OPERATIVO)

    resultado = calcular_liquidacion(
        dias_viaje=dias,
        noches_viaje=noches,
        tarifa_diaria=viaje.tarifa_diaria_chofer,
        bono_nocturno=viaje.bono_nocturno_chofer,
        total_adelantos_recibidos=total_adelantos,
        total_gastos_operativos=total_gastos_operativos,
    )

    liquidacion = (
        await db.execute(select(LiquidacionChofer).where(LiquidacionChofer.viaje_id == viaje_id))
    ).scalar_one_or_none()

    if liquidacion is None:
        liquidacion = LiquidacionChofer(viaje_id=viaje_id, chofer_id=viaje.chofer_id)
        db.add(liquidacion)

    liquidacion.dias_viaje = resultado.dias_viaje
    liquidacion.noches_viaje = resultado.noches_viaje
    liquidacion.tarifa_diaria = resultado.tarifa_diaria
    liquidacion.bono_nocturno = resultado.bono_nocturno
    liquidacion.monto_dietas = resultado.monto_dietas
    liquidacion.total_adelantos_recibidos = resultado.total_adelantos_recibidos
    liquidacion.total_gastos_operativos = resultado.total_gastos_operativos
    liquidacion.saldo_rendicion_cuentas = resultado.saldo_rendicion_cuentas
    liquidacion.neto_a_pagar_chofer = resultado.neto_a_pagar_chofer
    if liquidacion.estado is None:
        liquidacion.estado = EstadoLiquidacion.PENDIENTE

    await db.flush()
    return liquidacion
