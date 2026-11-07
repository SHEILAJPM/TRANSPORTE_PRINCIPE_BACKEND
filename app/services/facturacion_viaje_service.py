"""Factura o Boleta del flete, emitida al terminar el viaje (vía apisunat.pe).

El comprobante ya no nace con el viaje: cuando el viaje está FINALIZADO (mercadería
descargada), el usuario escribe el precio (con o sin IGV), elige factura o boleta,
revisa una vista previa y recién entonces se numera y se envía. Igual que con la
guía, el envío exige la huella de la vista previa confirmada.
"""

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cliente import Cliente
from app.models.comprobante import Factura, GuiaRemision
from app.models.cotizacion import Cotizacion
from app.models.empresa import Empresa
from app.models.enums import (
    EstadoSunat,
    EstadoViaje,
    ReceptorComprobante as Receptor,
    TipoDocumentoIdentidad,
    TipoDocumentoVenta,
)
from app.models.viaje import Viaje
from app.utils.correlativos import generar_numero_serie_sunat
from app.utils.dinero import a_decimal, redondear_moneda
from app.utils.fechas import ahora_peru

PORCENTAJE_IGV = Decimal("18.00")
# SUNAT exige identificar al comprador en boletas desde S/ 700.
LIMITE_BOLETA_SIN_DOCUMENTO = Decimal("700.00")
# Receptor genérico para boletas sin documento (Catálogo 06 "0"). Es la convención más
# usada por proveedores de facturación; confirmar con apisunat.pe en el primer envío.
RECEPTOR_VARIOS_TIPO = "0"
RECEPTOR_VARIOS_NUMERO = "00000000"
RECEPTOR_VARIOS_NOMBRE = "CLIENTES VARIOS"

# Detracción (SPOT) del servicio de transporte de bienes por vía terrestre: 4 % del
# total con IGV, solo en facturas cuyo total supere S/ 400. El depósito en el Banco de
# la Nación se hace en soles enteros (redondeo al entero más cercano).
PORCENTAJE_DETRACCION = Decimal("4.00")
MONTO_MINIMO_DETRACCION = Decimal("400.00")

SERIE_FACTURA_DEFAULT = "F001"
SERIE_BOLETA_DEFAULT = "B001"

ESTADOS_VIAJE_FACTURABLES = (EstadoViaje.FINALIZADO, EstadoViaje.LIQUIDADO)
_TIPOS_VENTA = (TipoDocumentoVenta.FACTURA, TipoDocumentoVenta.BOLETA)
_CODIGO_TIPO_DOCUMENTO = {TipoDocumentoIdentidad.RUC: "6", TipoDocumentoIdentidad.DNI: "1"}


class ViajeNoEncontradoError(Exception):
    pass


class ComprobanteNoEmitibleError(Exception):
    """El viaje no está en condiciones de facturarse (estado, comprobante previo, datos)."""


class HuellaComprobanteNoCoincideError(Exception):
    """Los datos cambiaron desde la vista previa que el usuario confirmó."""


@dataclass(frozen=True)
class EntradaComprobante:
    tipo_documento: TipoDocumentoVenta
    precio: Decimal
    precio_incluye_igv: bool
    receptor: Receptor = Receptor.CLIENTE
    descripcion: str | None = None


@dataclass(frozen=True)
class Montos:
    base: Decimal
    igv: Decimal
    total: Decimal
    porcentaje_igv: Decimal


def calcular_montos(precio, precio_incluye_igv: bool, porcentaje_igv: Decimal = PORCENTAJE_IGV) -> Montos:
    """Si el precio incluye IGV, se descompone (base = precio / 1.18; IGV = precio −
    base) para que el total sea exactamente lo escrito. Si no lo incluye, se le suma."""
    precio = redondear_moneda(precio)
    if precio_incluye_igv:
        base = redondear_moneda(precio / (1 + porcentaje_igv / 100))
        return Montos(base=base, igv=precio - base, total=precio, porcentaje_igv=porcentaje_igv)
    igv = redondear_moneda(precio * porcentaje_igv / 100)
    return Montos(base=precio, igv=igv, total=precio + igv, porcentaje_igv=porcentaje_igv)


@dataclass(frozen=True)
class Detraccion:
    aplica: bool
    porcentaje: Decimal
    monto: Decimal
    neto_a_cobrar: Decimal  # lo que el cliente paga directamente (total − detracción)
    motivo: str
    cuenta: str | None = None  # cuenta de detracciones del Banco de la Nación


def calcular_detraccion(tipo_documento: TipoDocumentoVenta, total: Decimal, cuenta: str | None = None) -> Detraccion:
    if tipo_documento != TipoDocumentoVenta.FACTURA:
        return Detraccion(False, PORCENTAJE_DETRACCION, Decimal("0.00"), total, "Las boletas no están sujetas a detracción")
    if total <= MONTO_MINIMO_DETRACCION:
        return Detraccion(
            False, PORCENTAJE_DETRACCION, Decimal("0.00"), total, f"No aplica: el total no supera S/ {MONTO_MINIMO_DETRACCION}"
        )
    monto = (total * PORCENTAJE_DETRACCION / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    destino = f"la cuenta N.° {cuenta}" if cuenta else "tu cuenta de detracciones"
    return Detraccion(
        True,
        PORCENTAJE_DETRACCION,
        monto,
        total - monto,
        f"El cliente deposita S/ {monto} en {destino} del Banco de la Nación",
        cuenta,
    )


@dataclass
class ComprobantePropuesto:
    viaje_id: uuid.UUID
    tipo_documento: TipoDocumentoVenta
    serie: str
    receptor_tipo_documento: str
    receptor_numero_documento: str
    receptor_razon_social: str
    descripcion: str
    precio_incluye_igv: bool
    montos: Montos
    detraccion: Detraccion
    guia_remision_id: uuid.UUID | None
    guia_remision: str | None
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    def huella(self) -> str:
        datos = asdict(self)
        datos.pop("errores")
        datos.pop("advertencias")
        contenido = json.dumps(datos, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(contenido.encode()).hexdigest()


@dataclass
class BorradorComprobante:
    viaje: Viaje
    cliente: Cliente
    tipo_sugerido: TipoDocumentoVenta
    precio_sugerido: Decimal | None
    precio_incluye_igv: bool
    origen_precio: str | None  # "COTIZACION" | "FLETE_ESTIMADO" | None
    descripcion_sugerida: str
    guia_remision: GuiaRemision | None
    cuenta_detracciones: str | None
    bloqueos: list[str]


@dataclass
class _Contexto:
    viaje: Viaje
    cliente: Cliente
    empresa: Empresa | None
    cotizacion: Cotizacion | None
    guia: GuiaRemision | None
    comprobantes: list[Factura]


async def _contexto(db: AsyncSession, viaje_id: uuid.UUID, empresa_id: uuid.UUID, bloquear: bool = False) -> _Contexto:
    stmt = select(Viaje).where(Viaje.id == viaje_id, Viaje.empresa_id == empresa_id)
    if bloquear:
        stmt = stmt.with_for_update()
    viaje = (await db.execute(stmt)).scalar_one_or_none()
    if viaje is None:
        raise ViajeNoEncontradoError("Viaje no encontrado")
    cliente = await db.get(Cliente, viaje.cliente_id)
    if cliente is None:
        raise ComprobanteNoEmitibleError("El cliente del viaje no existe")
    guia = (await db.execute(select(GuiaRemision).where(GuiaRemision.viaje_id == viaje.id))).scalar_one_or_none()
    comprobantes = list(
        (
            await db.execute(
                select(Factura)
                .where(Factura.viaje_id == viaje.id, Factura.tipo_documento.in_(_TIPOS_VENTA))
                .order_by(Factura.creado_en.desc())
            )
        ).scalars()
    )
    return _Contexto(
        viaje=viaje,
        cliente=cliente,
        empresa=await db.get(Empresa, viaje.empresa_id),
        cotizacion=await db.get(Cotizacion, viaje.cotizacion_id) if viaje.cotizacion_id else None,
        guia=guia,
        comprobantes=comprobantes,
    )


def _es_borrador_sin_enviar(factura: Factura) -> bool:
    """Comprobantes PENDIENTE creados automáticamente por el flujo anterior (al
    activar el viaje) que nunca salieron hacia SUNAT: se pueden descartar."""
    return (
        factura.estado_sunat == EstadoSunat.PENDIENTE
        and factura.enviado_en is None
        and factura.hash_cpe is None
        and factura.xml_url is None
        and factura.mensaje_sunat is None
    )


def comprobante_bloquea_nueva_emision(factura: Factura) -> bool:
    """Un comprobante aceptado, o enviado y aún en proceso, impide emitir otro para el
    mismo viaje. Los rechazados, anulados y borradores nunca enviados no bloquean."""
    return factura.estado_sunat == EstadoSunat.ACEPTADO or (
        factura.estado_sunat == EstadoSunat.PENDIENTE and not _es_borrador_sin_enviar(factura)
    )


def _bloqueos(ctx: _Contexto) -> list[str]:
    bloqueos = []
    guia_aceptada = ctx.guia is not None and ctx.guia.estado_sunat == EstadoSunat.ACEPTADO
    if ctx.viaje.estado == EstadoViaje.CANCELADO:
        bloqueos.append("El viaje está cancelado")
    elif ctx.viaje.estado not in ESTADOS_VIAJE_FACTURABLES and not guia_aceptada:
        bloqueos.append(
            "El comprobante se emite cuando el viaje está FINALIZADO (mercadería descargada) "
            "o cuando su guía de remisión ya fue aceptada por SUNAT"
        )
    for f in ctx.comprobantes:
        if not comprobante_bloquea_nueva_emision(f):
            continue
        etiqueta = f"{'La factura' if f.tipo_documento == TipoDocumentoVenta.FACTURA else 'La boleta'} {f.serie}-{f.numero}"
        if f.estado_sunat == EstadoSunat.ACEPTADO:
            bloqueos.append(f"{etiqueta} de este viaje ya fue aceptada por SUNAT")
        else:
            bloqueos.append(f"{etiqueta} ya fue enviada y está pendiente: reintenta su envío en lugar de emitir otra")
    return bloqueos


def _precio_sugerido(ctx: _Contexto) -> tuple[Decimal | None, bool, str | None]:
    if ctx.cotizacion is not None:
        total = redondear_moneda(a_decimal(ctx.cotizacion.precio_total) / ctx.cotizacion.cantidad_camiones)
        return total, True, "COTIZACION"
    if ctx.viaje.ingreso_flete_neto and a_decimal(ctx.viaje.ingreso_flete_neto) > 0:
        return redondear_moneda(ctx.viaje.ingreso_flete_neto), False, "FLETE_ESTIMADO"
    return None, True, None


def _descripcion_sugerida(ctx: _Contexto) -> str:
    base = (
        ctx.cotizacion.descripcion_servicio
        if ctx.cotizacion is not None
        else f"Servicio de transporte de carga por carretera de {ctx.viaje.origen_distrito} a {ctx.viaje.destino_distrito}"
    )
    referencia = f" — GRE {ctx.guia.serie}-{ctx.guia.numero}" if ctx.guia else ""
    return f"{base}{referencia}"[:500]


async def borrador(db: AsyncSession, viaje_id: uuid.UUID, empresa_id: uuid.UUID) -> BorradorComprobante:
    ctx = await _contexto(db, viaje_id, empresa_id)
    precio, incluye_igv, origen = _precio_sugerido(ctx)
    return BorradorComprobante(
        viaje=ctx.viaje,
        cliente=ctx.cliente,
        tipo_sugerido=(
            TipoDocumentoVenta.FACTURA if ctx.cliente.tipo_documento == TipoDocumentoIdentidad.RUC else TipoDocumentoVenta.BOLETA
        ),
        precio_sugerido=precio,
        precio_incluye_igv=incluye_igv,
        origen_precio=origen,
        descripcion_sugerida=_descripcion_sugerida(ctx),
        guia_remision=ctx.guia,
        cuenta_detracciones=ctx.empresa.cuenta_detracciones if ctx.empresa else None,
        bloqueos=_bloqueos(ctx),
    )


def _proponer(ctx: _Contexto, entrada: EntradaComprobante) -> ComprobantePropuesto:
    errores = _bloqueos(ctx)
    advertencias: list[str] = []
    es_factura = entrada.tipo_documento == TipoDocumentoVenta.FACTURA

    if entrada.precio <= 0:
        errores.append("El precio debe ser mayor a cero")
    montos = calcular_montos(max(entrada.precio, Decimal(0)), entrada.precio_incluye_igv)

    if entrada.receptor == Receptor.SIN_DOCUMENTO:
        if es_factura:
            errores.append("Una factura siempre se emite al RUC del cliente")
        if montos.total >= LIMITE_BOLETA_SIN_DOCUMENTO:
            errores.append(
                f"Una boleta de S/ {montos.total} debe identificar al comprador (sin documento solo hasta S/ 699.99)"
            )
        receptor = (RECEPTOR_VARIOS_TIPO, RECEPTOR_VARIOS_NUMERO, RECEPTOR_VARIOS_NOMBRE)
    else:
        receptor = (
            _CODIGO_TIPO_DOCUMENTO[ctx.cliente.tipo_documento],
            ctx.cliente.numero_documento,
            ctx.cliente.razon_social,
        )
        if es_factura and ctx.cliente.tipo_documento != TipoDocumentoIdentidad.RUC:
            errores.append("SUNAT no acepta facturas a clientes con DNI: emite una boleta")
        if not es_factura and ctx.cliente.tipo_documento == TipoDocumentoIdentidad.RUC:
            advertencias.append("El cliente tiene RUC: con boleta no podrá usar el IGV como crédito fiscal")

    descripcion = (entrada.descripcion or "").strip() or _descripcion_sugerida(ctx)

    precio_sugerido, incluye_sugerido, origen = _precio_sugerido(ctx)
    if origen == "COTIZACION" and precio_sugerido is not None:
        total_cotizado = calcular_montos(precio_sugerido, incluye_sugerido).total
        if total_cotizado != montos.total:
            advertencias.append(f"El total difiere de la cotización (S/ {total_cotizado})")
    if ctx.guia is None:
        advertencias.append("El viaje no tiene guía de remisión para relacionar")
    elif ctx.guia.estado_sunat != EstadoSunat.ACEPTADO:
        advertencias.append(f"La guía {ctx.guia.serie}-{ctx.guia.numero} todavía no fue aceptada por SUNAT")

    detraccion = calcular_detraccion(
        entrada.tipo_documento, montos.total, ctx.empresa.cuenta_detracciones if ctx.empresa else None
    )
    if detraccion.aplica and not detraccion.cuenta:
        advertencias.append(
            "Esta factura lleva detracción y no registraste la cuenta de detracciones del Banco de la Nación "
            "(Configuración de la empresa): no aparecerá en la factura y el cliente no sabrá dónde depositar"
        )
    if detraccion.aplica:
        advertencias.append(
            "La detracción se calcula y se registra en el sistema, pero todavía no se informa dentro del "
            "comprobante que se envía a SUNAT"
        )

    serie_factura = (ctx.empresa.serie_factura_default if ctx.empresa else None) or SERIE_FACTURA_DEFAULT
    return ComprobantePropuesto(
        viaje_id=ctx.viaje.id,
        tipo_documento=entrada.tipo_documento,
        serie=serie_factura if es_factura else SERIE_BOLETA_DEFAULT,
        receptor_tipo_documento=receptor[0],
        receptor_numero_documento=receptor[1],
        receptor_razon_social=receptor[2],
        descripcion=descripcion,
        precio_incluye_igv=entrada.precio_incluye_igv,
        montos=montos,
        detraccion=detraccion,
        guia_remision_id=ctx.guia.id if ctx.guia else None,
        guia_remision=f"{ctx.guia.serie}-{ctx.guia.numero}" if ctx.guia else None,
        errores=errores,
        advertencias=advertencias,
    )


async def vista_previa(
    db: AsyncSession, viaje_id: uuid.UUID, empresa_id: uuid.UUID, entrada: EntradaComprobante
) -> ComprobantePropuesto:
    return _proponer(await _contexto(db, viaje_id, empresa_id), entrada)


async def registrar(
    db: AsyncSession, viaje_id: uuid.UUID, empresa_id: uuid.UUID, entrada: EntradaComprobante, huella: str
) -> Factura:
    """Numera y guarda el comprobante confirmado, marcado como "enviándose". El envío a
    apisunat.pe lo hace el endpoint después de hacer commit de este registro, para que
    un corte de red no deje un comprobante enviado sin rastro en la base de datos."""
    ctx = await _contexto(db, viaje_id, empresa_id, bloquear=True)
    propuesto = _proponer(ctx, entrada)
    if propuesto.huella() != huella:
        raise HuellaComprobanteNoCoincideError(
            "Los datos del comprobante cambiaron desde que los revisaste. Vuelve a abrir la vista previa."
        )
    if propuesto.errores:
        raise ComprobanteNoEmitibleError("; ".join(propuesto.errores))

    for anterior in ctx.comprobantes:
        if _es_borrador_sin_enviar(anterior):
            await db.delete(anterior)

    ahora = ahora_peru()
    factura = Factura(
        empresa_id=ctx.viaje.empresa_id,
        viaje_id=ctx.viaje.id,
        cotizacion_id=ctx.viaje.cotizacion_id,
        cliente_id=ctx.cliente.id,
        guia_remision_id=propuesto.guia_remision_id,
        tipo_documento=propuesto.tipo_documento,
        serie=propuesto.serie,
        numero=await generar_numero_serie_sunat(db, tipo=propuesto.tipo_documento.value, serie=propuesto.serie),
        fecha_emision=ahora.date(),
        subtotal=propuesto.montos.base,
        igv=propuesto.montos.igv,
        total=propuesto.montos.total,
        precio_incluye_igv=propuesto.precio_incluye_igv,
        detraccion_porcentaje=propuesto.detraccion.porcentaje if propuesto.detraccion.aplica else None,
        detraccion_monto=propuesto.detraccion.monto if propuesto.detraccion.aplica else None,
        detraccion_cuenta=propuesto.detraccion.cuenta if propuesto.detraccion.aplica else None,
        receptor_tipo_documento=propuesto.receptor_tipo_documento,
        receptor_numero_documento=propuesto.receptor_numero_documento,
        receptor_razon_social=propuesto.receptor_razon_social,
        descripcion=propuesto.descripcion,
        estado_sunat=EstadoSunat.PENDIENTE,
        enviado_en=ahora,
    )
    db.add(factura)
    # El ingreso real del viaje es la base imponible del comprobante emitido.
    ctx.viaje.ingreso_flete_neto = propuesto.montos.base
    await db.flush()
    return factura
