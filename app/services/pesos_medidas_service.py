import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chofer import Chofer
from app.models.cliente import Cliente
from app.models.comprobante import GuiaRemision
from app.models.flota import Carreta, Tracto
from app.models.pesos_medidas import ConstanciaPesosMedidas
from app.utils.correlativos import generar_correlativo


class VehiculoNoEncontradoError(Exception):
    pass


@dataclass(frozen=True)
class DatosVehiculoAutocompletado:
    """Lo que el sistema autocompleta al seleccionar una placa (Tracto o Carreta),
    dejando cada campo editable manualmente en el formulario de la Constancia.
    """

    tipo: str  # TRACTO | CARRETA
    id: uuid.UUID
    placa: str
    largo_m: float
    ancho_m: float
    alto_m: float
    configuracion_vehicular: str
    tara_kg: float
    peso_bruto_max_kg: float


async def autocompletar_datos_vehiculo(db: AsyncSession, placa: str) -> DatosVehiculoAutocompletado:
    placa_normalizada = placa.strip().upper()

    tracto = (await db.execute(select(Tracto).where(Tracto.placa == placa_normalizada))).scalar_one_or_none()
    if tracto is not None:
        return DatosVehiculoAutocompletado(
            tipo="TRACTO",
            id=tracto.id,
            placa=tracto.placa,
            largo_m=float(tracto.largo_m),
            ancho_m=float(tracto.ancho_m),
            alto_m=float(tracto.alto_m),
            configuracion_vehicular=tracto.configuracion_vehicular,
            tara_kg=float(tracto.tara_kg or 0),
            peso_bruto_max_kg=float(tracto.peso_bruto_max_kg),
        )

    carreta = (await db.execute(select(Carreta).where(Carreta.placa == placa_normalizada))).scalar_one_or_none()
    if carreta is not None:
        return DatosVehiculoAutocompletado(
            tipo="CARRETA",
            id=carreta.id,
            placa=carreta.placa,
            largo_m=float(carreta.largo_m),
            ancho_m=float(carreta.ancho_m),
            alto_m=float(carreta.alto_m),
            configuracion_vehicular=carreta.configuracion_vehicular,
            tara_kg=float(carreta.tara_kg or 0),
            peso_bruto_max_kg=float(carreta.peso_bruto_max_kg),
        )

    raise VehiculoNoEncontradoError(f"No existe tracto ni carreta registrado con placa {placa_normalizada}")


async def construir_constancia_pesos_medidas(
    db: AsyncSession,
    *,
    empresa_id: uuid.UUID,
    guia_remision_id: uuid.UUID,
    viaje_id: uuid.UUID,
    tracto: Tracto,
    carreta: Carreta | None,
    chofer: Chofer,
    generador_carga_cliente_id: uuid.UUID,
    fecha_verificacion: datetime,
    tipo_control: str = "BALANZA",
    lugar_verificacion: str | None = None,
    precinto_seguridad: str | None = None,
    peso_bruto_kg: float | None = None,
    tara_kg: float | None = None,
) -> ConstanciaPesosMedidas:
    """Construye (sin persistir) la Constancia de Verificación de Pesos y Medidas
    (DS N.º 058-2003-MTC) autocompletando dimensiones, configuración vehicular y peso
    bruto máximo desde el tracto/carreta seleccionados. El peso bruto y la tara reales
    se toman de balanza (o, si aún no se pesa, se inicializan con la tara conocida de
    la unidad) y quedan editables manualmente vía `PATCH /pesos-medidas/{id}`.
    """
    tara_conocida = float(tracto.tara_kg or 0) + float((carreta.tara_kg if carreta else 0) or 0)
    tara_final = tara_kg if tara_kg is not None else tara_conocida
    peso_bruto_final = peso_bruto_kg if peso_bruto_kg is not None else tara_conocida

    return ConstanciaPesosMedidas(
        numero=await generar_correlativo(db, tipo="CONSTANCIA_PESOS_MEDIDAS", prefijo="CPM"),
        empresa_id=empresa_id,
        guia_remision_id=guia_remision_id,
        viaje_id=viaje_id,
        tracto_id=tracto.id,
        carreta_id=carreta.id if carreta else None,
        chofer_id=chofer.id,
        generador_carga_cliente_id=generador_carga_cliente_id,
        tipo_control=tipo_control,
        lugar_verificacion=lugar_verificacion,
        fecha_verificacion=fecha_verificacion,
        peso_bruto_kg=peso_bruto_final,
        tara_kg=tara_final,
        peso_neto_kg=max(peso_bruto_final - tara_final, 0),
        precinto_seguridad=precinto_seguridad,
        numero_licencia_chofer=chofer.licencia_numero,
        largo_m=carreta.largo_m if carreta else tracto.largo_m,
        ancho_m=carreta.ancho_m if carreta else tracto.ancho_m,
        alto_m=carreta.alto_m if carreta else tracto.alto_m,
        configuracion_vehicular=carreta.configuracion_vehicular if carreta else tracto.configuracion_vehicular,
        peso_bruto_max_kg=min(
            float(tracto.peso_bruto_max_kg), float(carreta.peso_bruto_max_kg) if carreta else float("inf")
        ),
    )


@dataclass(frozen=True)
class ConstanciaListItem:
    id: uuid.UUID
    numero: str
    viaje_id: uuid.UUID
    fecha_verificacion: datetime
    tracto_placa: str
    carreta_placa: str | None
    chofer_nombre: str
    generador_carga: str
    guia_remision_numero: str
    peso_bruto_kg: float
    peso_neto_kg: float
    peso_bruto_max_kg: float
    excede_limite: bool


async def listar_constancias(db: AsyncSession, *, empresa_id: uuid.UUID, q: str | None = None) -> list[ConstanciaListItem]:
    """Buscador del módulo de Pesos y Medidas: por número de constancia, placa
    (tracto o carreta) o número de serie de la Guía de Remisión vinculada."""
    stmt = (
        select(ConstanciaPesosMedidas, Tracto, Carreta, Chofer, Cliente, GuiaRemision)
        .join(Tracto, Tracto.id == ConstanciaPesosMedidas.tracto_id)
        .outerjoin(Carreta, Carreta.id == ConstanciaPesosMedidas.carreta_id)
        .join(Chofer, Chofer.id == ConstanciaPesosMedidas.chofer_id)
        .join(Cliente, Cliente.id == ConstanciaPesosMedidas.generador_carga_cliente_id)
        .join(GuiaRemision, GuiaRemision.id == ConstanciaPesosMedidas.guia_remision_id)
        .where(ConstanciaPesosMedidas.empresa_id == empresa_id)
        .order_by(ConstanciaPesosMedidas.fecha_verificacion.desc())
    )

    if q:
        patron = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ConstanciaPesosMedidas.numero.ilike(patron),
                Tracto.placa.ilike(patron),
                Carreta.placa.ilike(patron),
                GuiaRemision.numero.ilike(patron),
            )
        )

    filas = (await db.execute(stmt)).all()

    return [
        ConstanciaListItem(
            id=constancia.id,
            numero=constancia.numero,
            viaje_id=constancia.viaje_id,
            fecha_verificacion=constancia.fecha_verificacion,
            tracto_placa=tracto.placa,
            carreta_placa=carreta.placa if carreta else None,
            chofer_nombre=f"{chofer.nombres} {chofer.apellidos}",
            generador_carga=cliente.razon_social,
            guia_remision_numero=f"{guia.serie}-{guia.numero}",
            peso_bruto_kg=float(constancia.peso_bruto_kg),
            peso_neto_kg=float(constancia.peso_neto_kg),
            peso_bruto_max_kg=float(constancia.peso_bruto_max_kg),
            excede_limite=float(constancia.peso_bruto_kg) > float(constancia.peso_bruto_max_kg),
        )
        for constancia, tracto, carreta, chofer, cliente, guia in filas
    ]
