import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chofer import Chofer
from app.models.cliente import Cliente
from app.models.comprobante import Factura, GuiaRemision
from app.models.cotizacion import CONDICIONES_COMERCIALES_DEFAULT, Cotizacion
from app.models.enums import (
    EstadoCotizacion,
    EstadoSunat,
    EstadoViaje,
    ModalidadViaje,
    TipoDocumentoIdentidad,
    TipoDocumentoVenta,
)
from app.models.flota import Carreta, Tracto
from app.models.pesos_medidas import ConstanciaPesosMedidas
from app.models.viaje import Viaje
from app.services.pesos_medidas_service import construir_constancia_pesos_medidas
from app.utils.correlativos import generar_correlativo, generar_numero_serie_sunat
from app.utils.dinero import a_decimal, redondear_moneda


class CotizacionYaConvertidaError(Exception):
    pass


class CotizacionNoAprobadaError(Exception):
    pass


class AsignacionIncompletaError(Exception):
    pass


class TransicionEstadoInvalidaError(Exception):
    pass


class ModalidadInconsistenteError(Exception):
    """La modalidad (CON_RUC/SIN_RUC) no coincide con el tipo de documento del
    cliente: SUNAT rechaza una Factura emitida a un cliente con DNI."""


# Transiciones de estado permitidas para una cotización (la conversión a viaje se
# maneja aparte, en `convertir_cotizacion_a_viajes`, y deja el estado en CONVERTIDA).
_TRANSICIONES_VALIDAS: dict[EstadoCotizacion, tuple[EstadoCotizacion, ...]] = {
    EstadoCotizacion.BORRADOR: (EstadoCotizacion.ENVIADA, EstadoCotizacion.VENCIDA),
    EstadoCotizacion.ENVIADA: (EstadoCotizacion.APROBADA, EstadoCotizacion.RECHAZADA, EstadoCotizacion.VENCIDA),
    EstadoCotizacion.APROBADA: (EstadoCotizacion.RECHAZADA, EstadoCotizacion.VENCIDA),
    EstadoCotizacion.RECHAZADA: (),
    EstadoCotizacion.CONVERTIDA: (),
    EstadoCotizacion.VENCIDA: (),
}


@dataclass
class DatosCotizacion:
    cliente_id: uuid.UUID
    descripcion_servicio: str
    origen_direccion: str
    origen_distrito: str
    origen_provincia: str
    origen_departamento: str
    destino_direccion: str
    destino_distrito: str
    destino_provincia: str
    destino_departamento: str
    peso_tm: float
    precio_base: float
    cantidad_camiones: int = 1
    porcentaje_igv: float = 18.00
    condiciones_comerciales: str = CONDICIONES_COMERCIALES_DEFAULT
    validez_dias: int = 7
    fecha_emision: date | None = None


async def crear_cotizacion(
    db: AsyncSession, datos: DatosCotizacion, empresa_id: uuid.UUID, usuario_id: uuid.UUID
) -> Cotizacion:
    """Genera una Cotización en estado BORRADOR, calculando IGV (18% por defecto)
    y precio total a partir del precio base."""
    precio_base = redondear_moneda(datos.precio_base)
    monto_igv = redondear_moneda(precio_base * a_decimal(datos.porcentaje_igv) / a_decimal(100))
    precio_total = redondear_moneda(precio_base + monto_igv)

    cotizacion = Cotizacion(
        numero=await generar_correlativo(db, tipo="COTIZACION", prefijo="COT"),
        empresa_id=empresa_id,
        cliente_id=datos.cliente_id,
        usuario_id=usuario_id,
        descripcion_servicio=datos.descripcion_servicio,
        origen_direccion=datos.origen_direccion,
        origen_distrito=datos.origen_distrito,
        origen_provincia=datos.origen_provincia,
        origen_departamento=datos.origen_departamento,
        destino_direccion=datos.destino_direccion,
        destino_distrito=datos.destino_distrito,
        destino_provincia=datos.destino_provincia,
        destino_departamento=datos.destino_departamento,
        cantidad_camiones=datos.cantidad_camiones,
        peso_tm=datos.peso_tm,
        precio_base=precio_base,
        porcentaje_igv=datos.porcentaje_igv,
        monto_igv=monto_igv,
        precio_total=precio_total,
        condiciones_comerciales=datos.condiciones_comerciales,
        validez_dias=datos.validez_dias,
        fecha_emision=datos.fecha_emision or datetime.now(timezone.utc).date(),
        estado=EstadoCotizacion.BORRADOR,
    )
    db.add(cotizacion)
    await db.flush()
    return cotizacion


async def cambiar_estado_cotizacion(db: AsyncSession, cotizacion: Cotizacion, nuevo_estado: EstadoCotizacion) -> Cotizacion:
    permitidos = _TRANSICIONES_VALIDAS.get(cotizacion.estado, ())
    if nuevo_estado not in permitidos:
        raise TransicionEstadoInvalidaError(
            f"No se puede pasar la cotización {cotizacion.numero} de {cotizacion.estado.value} a {nuevo_estado.value}"
        )
    cotizacion.estado = nuevo_estado
    await db.flush()
    return cotizacion


@dataclass
class AsignacionUnidad:
    """Unidad física + chofer que ejecutará una de las cantidad_camiones del servicio cotizado."""

    tracto_id: uuid.UUID
    chofer_id: uuid.UUID
    fecha_salida_programada: datetime
    carreta_id: uuid.UUID | None = None
    tarifa_diaria_chofer: float | None = None  # si es None, se usa Chofer.tarifa_diaria_default
    bono_nocturno_chofer: float | None = None  # si es None, se usa Chofer.bono_nocturno_default
    precinto_seguridad: str | None = None
    lugar_verificacion_pesos: str | None = None
    origen_ubigeo: str | None = None
    destino_ubigeo: str | None = None


@dataclass
class ResultadoConversion:
    viaje: Viaje
    guia_remision: GuiaRemision
    factura: Factura
    constancia_pesos_medidas: ConstanciaPesosMedidas


async def convertir_cotizacion_a_viajes(
    db: AsyncSession,
    cotizacion_id: uuid.UUID,
    asignaciones: list[AsignacionUnidad],
    empresa_id: uuid.UUID,
    propietario_usuario_id: uuid.UUID,
    modalidad: ModalidadViaje,
    serie_guia_remision: str = "V001",
    serie_factura: str = "F001",
    serie_boleta: str = "B001",
) -> list[ResultadoConversion]:
    """Botón de Conversión de 1 Clic.

    Al aprobarse una Cotización, este algoritmo traslada TODOS sus datos (cliente,
    ruta, peso, precio, IGV y condiciones comerciales) hacia:
      1) Uno o más Viaje (uno por cada camión de `cantidad_camiones`),
      2) La Guía de Remisión Electrónica de cada viaje,
      3) La Factura correspondiente,
      4) La Constancia de Verificación de Pesos y Medidas (DS 058-2003-MTC),
    sin que el usuario vuelva a digitar ningún dato ya capturado en la cotización.
    Todo ocurre en una sola transacción: si algo falla, no queda nada a medias.
    """
    cotizacion = await db.get(Cotizacion, cotizacion_id)
    if cotizacion is None:
        raise ValueError("Cotización no encontrada")
    cliente = await db.get(Cliente, cotizacion.cliente_id)
    if cliente is None:
        raise ValueError("El cliente de esta cotización no existe")
    if modalidad == ModalidadViaje.CON_RUC and cliente.tipo_documento != TipoDocumentoIdentidad.RUC:
        raise ModalidadInconsistenteError(
            "La modalidad CON_RUC requiere un cliente con RUC (SUNAT no acepta facturas a clientes con DNI)"
        )
    if cotizacion.estado == EstadoCotizacion.CONVERTIDA:
        raise CotizacionYaConvertidaError(f"La cotización {cotizacion.numero} ya fue convertida a viaje")
    if cotizacion.estado != EstadoCotizacion.APROBADA:
        raise CotizacionNoAprobadaError("Solo se puede convertir una cotización en estado APROBADA")
    if len(asignaciones) != cotizacion.cantidad_camiones:
        raise AsignacionIncompletaError(
            f"La cotización {cotizacion.numero} requiere {cotizacion.cantidad_camiones} unidad(es); "
            f"se recibieron {len(asignaciones)} asignación(es)"
        )

    # El peso y el ingreso cotizados se distribuyen en partes iguales entre las unidades asignadas.
    peso_tm_por_camion = cotizacion.peso_tm / cotizacion.cantidad_camiones
    precio_base_por_camion = cotizacion.precio_base / cotizacion.cantidad_camiones
    igv_por_camion = cotizacion.monto_igv / cotizacion.cantidad_camiones
    total_por_camion = cotizacion.precio_total / cotizacion.cantidad_camiones

    resultados: list[ResultadoConversion] = []

    for asignacion in asignaciones:
        tracto = await db.get(Tracto, asignacion.tracto_id)
        chofer = await db.get(Chofer, asignacion.chofer_id)
        carreta = await db.get(Carreta, asignacion.carreta_id) if asignacion.carreta_id else None
        if tracto is None:
            raise ValueError(f"Tracto {asignacion.tracto_id} no encontrado")
        if chofer is None:
            raise ValueError(f"Chofer {asignacion.chofer_id} no encontrado")

        viaje = Viaje(
            numero=await generar_correlativo(db, tipo="VIAJE", prefijo="VJ"),
            empresa_id=empresa_id,
            cotizacion_id=cotizacion.id,
            cliente_id=cotizacion.cliente_id,
            modalidad=modalidad,
            tracto_id=tracto.id,
            carreta_id=carreta.id if carreta else None,
            chofer_id=chofer.id,
            propietario_usuario_id=propietario_usuario_id,
            origen_direccion=cotizacion.origen_direccion,
            origen_distrito=cotizacion.origen_distrito,
            origen_provincia=cotizacion.origen_provincia,
            origen_departamento=cotizacion.origen_departamento,
            origen_ubigeo=asignacion.origen_ubigeo,
            destino_direccion=cotizacion.destino_direccion,
            destino_distrito=cotizacion.destino_distrito,
            destino_provincia=cotizacion.destino_provincia,
            destino_departamento=cotizacion.destino_departamento,
            destino_ubigeo=asignacion.destino_ubigeo,
            peso_tm=peso_tm_por_camion,
            fecha_salida_programada=asignacion.fecha_salida_programada,
            tarifa_diaria_chofer=asignacion.tarifa_diaria_chofer or chofer.tarifa_diaria_default,
            bono_nocturno_chofer=asignacion.bono_nocturno_chofer or chofer.bono_nocturno_default,
            ingreso_flete_neto=precio_base_por_camion,
            estado=EstadoViaje.PROGRAMADO,
        )
        db.add(viaje)
        await db.flush()  # asigna viaje.id para las FK de los documentos siguientes

        guia_remision = GuiaRemision(
            empresa_id=empresa_id,
            viaje_id=viaje.id,
            cotizacion_id=cotizacion.id,
            cliente_id=cotizacion.cliente_id,
            serie=serie_guia_remision,
            numero=await generar_numero_serie_sunat(db, tipo="GUIA_REMISION", serie=serie_guia_remision),
            fecha_emision=asignacion.fecha_salida_programada.date(),
            motivo_traslado="VENTA",
            peso_bruto_total_kg=float(peso_tm_por_camion) * 1000,
            estado_sunat=EstadoSunat.PENDIENTE,
        )
        db.add(guia_remision)
        await db.flush()

        es_con_ruc = modalidad == ModalidadViaje.CON_RUC
        tipo_documento = TipoDocumentoVenta.FACTURA if es_con_ruc else TipoDocumentoVenta.BOLETA
        serie_documento = serie_factura if es_con_ruc else serie_boleta
        factura = Factura(
            empresa_id=empresa_id,
            viaje_id=viaje.id,
            cotizacion_id=cotizacion.id,
            cliente_id=cotizacion.cliente_id,
            guia_remision_id=guia_remision.id,
            tipo_documento=tipo_documento,
            serie=serie_documento,
            numero=await generar_numero_serie_sunat(db, tipo=tipo_documento.value, serie=serie_documento),
            fecha_emision=asignacion.fecha_salida_programada.date(),
            subtotal=precio_base_por_camion,
            igv=igv_por_camion,
            total=total_por_camion,
            estado_sunat=EstadoSunat.PENDIENTE,
        )
        db.add(factura)

        constancia = await construir_constancia_pesos_medidas(
            db,
            empresa_id=empresa_id,
            guia_remision_id=guia_remision.id,
            viaje_id=viaje.id,
            tracto=tracto,
            carreta=carreta,
            chofer=chofer,
            generador_carga_cliente_id=cotizacion.cliente_id,
            fecha_verificacion=asignacion.fecha_salida_programada,
            lugar_verificacion=asignacion.lugar_verificacion_pesos,
            precinto_seguridad=asignacion.precinto_seguridad,
        )
        db.add(constancia)

        resultados.append(
            ResultadoConversion(
                viaje=viaje, guia_remision=guia_remision, factura=factura, constancia_pesos_medidas=constancia
            )
        )

    cotizacion.estado = EstadoCotizacion.CONVERTIDA
    cotizacion.convertida_en = datetime.now(timezone.utc)

    await db.flush()
    return resultados
