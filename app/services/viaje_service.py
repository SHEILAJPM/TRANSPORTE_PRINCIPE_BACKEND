import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chofer import Chofer
from app.models.cliente import Cliente
from app.models.comprobante import GuiaRemision
from app.models.enums import EstadoSunat, EstadoViaje, ModalidadViaje, TipoDocumentoIdentidad
from app.models.flota import Carreta, Tracto
from app.models.pesos_medidas import ConstanciaPesosMedidas
from app.models.viaje import Viaje
from app.services.pesos_medidas_service import construir_constancia_pesos_medidas
from app.utils.correlativos import generar_correlativo, generar_numero_serie_sunat


class ModalidadInconsistenteError(Exception):
    """La modalidad (CON_RUC/SIN_RUC) no coincide con el tipo de documento del
    cliente: SUNAT rechaza una Factura emitida a un cliente con DNI."""


@dataclass
class ActivacionViaje:
    """Datos que el propietario ingresa al activar un viaje directamente (sin
    pasar por una Cotización previa): módulo 5, "Activación de Viaje por el Propietario".
    """

    empresa_id: uuid.UUID
    propietario_usuario_id: uuid.UUID
    cliente_id: uuid.UUID
    # CON_RUC -> Factura; SIN_RUC -> Boleta. None = se deduce del documento del cliente.
    modalidad: ModalidadViaje | None
    tracto_id: uuid.UUID
    chofer_id: uuid.UUID
    origen_direccion: str
    origen_distrito: str
    origen_provincia: str
    origen_departamento: str
    destino_direccion: str
    destino_distrito: str
    destino_provincia: str
    destino_departamento: str
    peso_tm: float
    fecha_salida_programada: datetime
    ingreso_flete_neto: float | None = None
    carreta_id: uuid.UUID | None = None
    origen_ubigeo: str | None = None
    destino_ubigeo: str | None = None
    tarifa_diaria_chofer: float | None = None
    bono_nocturno_chofer: float | None = None
    precinto_seguridad: str | None = None
    lugar_verificacion_pesos: str | None = None
    numero_bultos: int | None = None
    motivo_traslado: str | None = None
    destinatario_tipo_documento: str | None = None
    destinatario_numero_documento: str | None = None
    destinatario_razon_social: str | None = None
    remitente_guia_ruc_emisor: str | None = None
    remitente_guia_serie: str | None = None
    remitente_guia_numero: str | None = None
    bienes: list[dict] | None = None


@dataclass
class ResultadoActivacion:
    viaje: Viaje
    guia_remision: GuiaRemision
    constancia_pesos_medidas: ConstanciaPesosMedidas


async def activar_viaje(
    db: AsyncSession,
    datos: ActivacionViaje,
    serie_guia_remision: str = "V001",
) -> ResultadoActivacion:
    """Activa un viaje sin cotización previa. Igual que la conversión de 1 clic,
    genera en una sola transacción la Guía de Remisión y la Constancia de Pesos y
    Medidas (obligatorias para transportar carga). La Factura/Boleta no se genera
    aquí: se emite al terminar el viaje (facturacion_viaje_service).
    """
    tracto = await db.get(Tracto, datos.tracto_id)
    chofer = await db.get(Chofer, datos.chofer_id)
    carreta = await db.get(Carreta, datos.carreta_id) if datos.carreta_id else None
    cliente = await db.get(Cliente, datos.cliente_id)
    if tracto is None:
        raise ValueError(f"Tracto {datos.tracto_id} no encontrado")
    if chofer is None:
        raise ValueError(f"Chofer {datos.chofer_id} no encontrado")
    if cliente is None:
        raise ValueError(f"Cliente {datos.cliente_id} no encontrado")
    modalidad = datos.modalidad or (
        ModalidadViaje.CON_RUC if cliente.tipo_documento == TipoDocumentoIdentidad.RUC else ModalidadViaje.SIN_RUC
    )
    if modalidad == ModalidadViaje.CON_RUC and cliente.tipo_documento != TipoDocumentoIdentidad.RUC:
        raise ModalidadInconsistenteError(
            "La modalidad CON_RUC requiere un cliente con RUC (SUNAT no acepta facturas a clientes con DNI)"
        )

    viaje = Viaje(
        numero=await generar_correlativo(db, tipo="VIAJE", prefijo="VJ"),
        empresa_id=datos.empresa_id,
        cotizacion_id=None,
        cliente_id=datos.cliente_id,
        modalidad=modalidad,
        tracto_id=tracto.id,
        carreta_id=carreta.id if carreta else None,
        chofer_id=chofer.id,
        propietario_usuario_id=datos.propietario_usuario_id,
        origen_direccion=datos.origen_direccion,
        origen_distrito=datos.origen_distrito,
        origen_provincia=datos.origen_provincia,
        origen_departamento=datos.origen_departamento,
        origen_ubigeo=datos.origen_ubigeo,
        destino_direccion=datos.destino_direccion,
        destino_distrito=datos.destino_distrito,
        destino_provincia=datos.destino_provincia,
        destino_departamento=datos.destino_departamento,
        destino_ubigeo=datos.destino_ubigeo,
        peso_tm=datos.peso_tm,
        fecha_salida_programada=datos.fecha_salida_programada,
        tarifa_diaria_chofer=datos.tarifa_diaria_chofer or chofer.tarifa_diaria_default,
        bono_nocturno_chofer=datos.bono_nocturno_chofer or chofer.bono_nocturno_default,
        # Flete estimado (opcional); el definitivo se fija al emitir la Factura/Boleta.
        ingreso_flete_neto=datos.ingreso_flete_neto or 0,
        estado=EstadoViaje.PROGRAMADO,
    )
    db.add(viaje)
    await db.flush()

    guia_remision = GuiaRemision(
        empresa_id=datos.empresa_id,
        viaje_id=viaje.id,
        cotizacion_id=None,
        cliente_id=datos.cliente_id,
        serie=serie_guia_remision,
        numero=await generar_numero_serie_sunat(db, tipo="GUIA_REMISION", serie=serie_guia_remision),
        fecha_emision=datos.fecha_salida_programada.date(),
        motivo_traslado=datos.motivo_traslado or "VENTA",
        peso_bruto_total_kg=float(datos.peso_tm) * 1000,
        numero_bultos=datos.numero_bultos,
        destinatario_tipo_documento=datos.destinatario_tipo_documento,
        destinatario_numero_documento=datos.destinatario_numero_documento,
        destinatario_razon_social=datos.destinatario_razon_social,
        remitente_guia_ruc_emisor=datos.remitente_guia_ruc_emisor,
        remitente_guia_serie=datos.remitente_guia_serie,
        remitente_guia_numero=datos.remitente_guia_numero,
        bienes=datos.bienes,
        estado_sunat=EstadoSunat.PENDIENTE,
    )
    db.add(guia_remision)
    await db.flush()

    constancia = await construir_constancia_pesos_medidas(
        db,
        empresa_id=datos.empresa_id,
        guia_remision_id=guia_remision.id,
        viaje_id=viaje.id,
        tracto=tracto,
        carreta=carreta,
        chofer=chofer,
        generador_carga_cliente_id=datos.cliente_id,
        fecha_verificacion=datos.fecha_salida_programada,
        lugar_verificacion=datos.lugar_verificacion_pesos,
        precinto_seguridad=datos.precinto_seguridad,
    )
    db.add(constancia)
    await db.flush()

    return ResultadoActivacion(
        viaje=viaje, guia_remision=guia_remision, constancia_pesos_medidas=constancia
    )
