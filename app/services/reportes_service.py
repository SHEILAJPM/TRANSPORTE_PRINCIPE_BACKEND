import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cliente import Cliente
from app.models.flota import Carreta, Tracto
from app.models.gasto_general import GastoGeneral
from app.models.gasto_viaje import GastoViaje
from app.models.liquidacion import LiquidacionChofer
from app.models.mantenimiento import MantenimientoVehiculo
from app.models.viaje import Viaje
from app.services.liquidacion_service import TIPOS_GASTO_OPERATIVO, sumar_gastos_por_tipo
from app.utils.dinero import a_decimal, redondear_moneda


@dataclass(frozen=True)
class RentabilidadViaje:
    ingresos_netos_flete: Decimal
    total_gastos_operativos: Decimal
    monto_dietas_chofer: Decimal
    egresos_totales: Decimal
    ganancia_neta: Decimal


async def calcular_rentabilidad_viaje(db: AsyncSession, viaje_id: uuid.UUID) -> RentabilidadViaje:
    """Consolidado financiero por viaje: Ingresos Netos del Flete - Egresos Totales = Ganancia Neta.

    Egresos Totales = gastos operativos reales (combustible/peaje/viático/otro) + el costo
    de las dietas del chofer. Los adelantos NO son un egreso: son efectivo de la empresa que
    ya queda reflejado, o bien en gastos operativos (si se gastó) o en la liquidación (si se
    debe devolver) — sumarlos aquí duplicaría el costo.
    """
    viaje = await db.get(Viaje, viaje_id)
    if viaje is None:
        raise ValueError("Viaje no encontrado")

    total_gastos_operativos = await sumar_gastos_por_tipo(db, viaje_id, TIPOS_GASTO_OPERATIVO)

    liquidacion = (
        await db.execute(select(LiquidacionChofer).where(LiquidacionChofer.viaje_id == viaje_id))
    ).scalar_one_or_none()
    monto_dietas = a_decimal(liquidacion.monto_dietas) if liquidacion else Decimal("0")

    ingresos_netos_flete = a_decimal(viaje.ingreso_flete_neto)
    egresos_totales = redondear_moneda(total_gastos_operativos + monto_dietas)
    ganancia_neta = redondear_moneda(ingresos_netos_flete - egresos_totales)

    return RentabilidadViaje(
        ingresos_netos_flete=redondear_moneda(ingresos_netos_flete),
        total_gastos_operativos=redondear_moneda(total_gastos_operativos),
        monto_dietas_chofer=redondear_moneda(monto_dietas),
        egresos_totales=egresos_totales,
        ganancia_neta=ganancia_neta,
    )


@dataclass(frozen=True)
class ViajeRentabilidadItem:
    """Una fila del buscador avanzado de cobros/rentabilidad (módulo 6): historial
    geográfico y financiero filtrable por ciudad, cliente, placa y rango de fechas.
    """

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


async def buscar_viajes_rentabilidad(
    db: AsyncSession,
    *,
    empresa_id: uuid.UUID,
    cliente_id: uuid.UUID | None = None,
    placa: str | None = None,
    ciudad: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
) -> list[ViajeRentabilidadItem]:
    """Buscador avanzado de cobros: consolida ingreso, egresos y ganancia neta por
    viaje en una sola consulta (agregando gastos operativos por subquery, evitando N+1),
    filtrable por cliente, placa (tracto o carreta), ciudad de origen/destino y fechas.
    """
    gastos_subq = (
        select(GastoViaje.viaje_id, func.coalesce(func.sum(GastoViaje.monto), 0).label("total_gastos"))
        .where(GastoViaje.tipo_gasto.in_(TIPOS_GASTO_OPERATIVO))
        .group_by(GastoViaje.viaje_id)
        .subquery()
    )

    stmt = (
        select(
            Viaje,
            Cliente.razon_social,
            Tracto.placa,
            Carreta.placa,
            gastos_subq.c.total_gastos,
            LiquidacionChofer.monto_dietas,
        )
        .join(Cliente, Cliente.id == Viaje.cliente_id)
        .join(Tracto, Tracto.id == Viaje.tracto_id)
        .outerjoin(Carreta, Carreta.id == Viaje.carreta_id)
        .outerjoin(gastos_subq, gastos_subq.c.viaje_id == Viaje.id)
        .outerjoin(LiquidacionChofer, LiquidacionChofer.viaje_id == Viaje.id)
        .where(Viaje.empresa_id == empresa_id)
    )

    if cliente_id is not None:
        stmt = stmt.where(Viaje.cliente_id == cliente_id)
    if placa:
        patron_placa = f"%{placa.strip().upper()}%"
        stmt = stmt.where(or_(Tracto.placa.ilike(patron_placa), Carreta.placa.ilike(patron_placa)))
    if ciudad:
        patron_ciudad = f"%{ciudad.strip()}%"
        stmt = stmt.where(
            or_(
                Viaje.origen_distrito.ilike(patron_ciudad),
                Viaje.origen_provincia.ilike(patron_ciudad),
                Viaje.origen_departamento.ilike(patron_ciudad),
                Viaje.destino_distrito.ilike(patron_ciudad),
                Viaje.destino_provincia.ilike(patron_ciudad),
                Viaje.destino_departamento.ilike(patron_ciudad),
            )
        )
    if fecha_desde is not None:
        stmt = stmt.where(Viaje.fecha_salida_programada >= fecha_desde)
    if fecha_hasta is not None:
        stmt = stmt.where(Viaje.fecha_salida_programada <= fecha_hasta)

    stmt = stmt.order_by(Viaje.fecha_salida_programada.desc())

    filas = (await db.execute(stmt)).all()

    resultados: list[ViajeRentabilidadItem] = []
    for viaje, cliente_razon_social, placa_tracto, placa_carreta, total_gastos, monto_dietas in filas:
        ingresos = a_decimal(viaje.ingreso_flete_neto)
        gastos_operativos = redondear_moneda(total_gastos or 0)
        dietas = redondear_moneda(monto_dietas or 0)
        egresos_totales = redondear_moneda(gastos_operativos + dietas)
        resultados.append(
            ViajeRentabilidadItem(
                id=viaje.id,
                numero=viaje.numero,
                estado=viaje.estado.value,
                fecha_salida_programada=viaje.fecha_salida_programada,
                cliente_razon_social=cliente_razon_social,
                placa_tracto=placa_tracto,
                placa_carreta=placa_carreta,
                origen=f"{viaje.origen_distrito}, {viaje.origen_provincia}, {viaje.origen_departamento}",
                destino=f"{viaje.destino_distrito}, {viaje.destino_provincia}, {viaje.destino_departamento}",
                ingresos_netos_flete=redondear_moneda(ingresos),
                total_gastos_operativos=gastos_operativos,
                monto_dietas_chofer=dietas,
                egresos_totales=egresos_totales,
                ganancia_neta=redondear_moneda(ingresos - egresos_totales),
            )
        )
    return resultados


@dataclass(frozen=True)
class ResumenFinanciero:
    """P&L general de la empresa para un rango de fechas (no por viaje): junta los
    egresos de viaje, dietas, mantenimiento de flota y egresos generales — los cuatro
    "baldes" de costo del negocio — contra el total de fletes cobrados en el período.
    """

    ingresos_totales: Decimal
    egresos_operativos_viajes: Decimal
    dietas_choferes: Decimal
    mantenimiento_flota: Decimal
    egresos_generales: Decimal
    egresos_totales: Decimal
    ganancia_neta: Decimal


async def calcular_resumen_financiero(
    db: AsyncSession,
    *,
    empresa_id: uuid.UUID,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
) -> ResumenFinanciero:
    def _rango(columna, stmt):
        if fecha_desde is not None:
            stmt = stmt.where(columna >= fecha_desde)
        if fecha_hasta is not None:
            stmt = stmt.where(columna <= fecha_hasta)
        return stmt

    # Ingresos: fletes de los viajes cuya salida programada cae en el período.
    stmt_ingresos = _rango(
        Viaje.fecha_salida_programada,
        select(func.coalesce(func.sum(Viaje.ingreso_flete_neto), 0)).where(Viaje.empresa_id == empresa_id),
    )
    ingresos_totales = a_decimal((await db.execute(stmt_ingresos)).scalar_one())

    # Gastos operativos de viaje: por la fecha real en que se incurrió el gasto.
    stmt_gastos_viaje = _rango(
        GastoViaje.fecha,
        select(func.coalesce(func.sum(GastoViaje.monto), 0))
        .select_from(GastoViaje)
        .join(Viaje, Viaje.id == GastoViaje.viaje_id)
        .where(Viaje.empresa_id == empresa_id, GastoViaje.tipo_gasto.in_(TIPOS_GASTO_OPERATIVO)),
    )
    egresos_operativos_viajes = a_decimal((await db.execute(stmt_gastos_viaje)).scalar_one())

    # Dietas: por la fecha de salida del viaje que las generó.
    stmt_dietas = _rango(
        Viaje.fecha_salida_programada,
        select(func.coalesce(func.sum(LiquidacionChofer.monto_dietas), 0))
        .select_from(LiquidacionChofer)
        .join(Viaje, Viaje.id == LiquidacionChofer.viaje_id)
        .where(Viaje.empresa_id == empresa_id),
    )
    dietas_choferes = a_decimal((await db.execute(stmt_dietas)).scalar_one())

    # Mantenimiento de flota: la flota no está particionada por empresa en este
    # sistema (single-tenant en la práctica), así que se suma todo el mantenimiento
    # del período, igual que ya lo hace el módulo de Flota.
    stmt_mantenimiento = _rango(
        MantenimientoVehiculo.fecha_realizado,
        select(func.coalesce(func.sum(MantenimientoVehiculo.costo), 0)),
    )
    mantenimiento_flota = a_decimal((await db.execute(stmt_mantenimiento)).scalar_one())

    # Egresos generales de la empresa (alquiler, seguros, sueldos, servicios, etc.)
    stmt_generales = _rango(
        GastoGeneral.fecha,
        select(func.coalesce(func.sum(GastoGeneral.monto), 0)).where(GastoGeneral.empresa_id == empresa_id),
    )
    egresos_generales = a_decimal((await db.execute(stmt_generales)).scalar_one())

    egresos_totales = redondear_moneda(
        egresos_operativos_viajes + dietas_choferes + mantenimiento_flota + egresos_generales
    )

    return ResumenFinanciero(
        ingresos_totales=redondear_moneda(ingresos_totales),
        egresos_operativos_viajes=redondear_moneda(egresos_operativos_viajes),
        dietas_choferes=redondear_moneda(dietas_choferes),
        mantenimiento_flota=redondear_moneda(mantenimiento_flota),
        egresos_generales=redondear_moneda(egresos_generales),
        egresos_totales=egresos_totales,
        ganancia_neta=redondear_moneda(ingresos_totales - egresos_totales),
    )
