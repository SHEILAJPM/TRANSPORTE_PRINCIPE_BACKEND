import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.models.enums import EstadoVehiculo, TipoCarreta, TipoMantenimiento


class TractoCreateRequest(BaseModel):
    placa: str = Field(min_length=6, max_length=10)
    marca: str
    modelo: str | None = None
    anio_fabricacion: int | None = None
    numero_motor: str | None = None
    numero_chasis: str | None = None
    largo_m: float
    ancho_m: float
    alto_m: float
    configuracion_vehicular: str
    numero_ejes: int | None = None
    tara_kg: float | None = None
    peso_bruto_max_kg: float
    kilometraje_actual: int = 0
    soat_vencimiento: date | None = None
    citv_vencimiento: date | None = None
    mtc_habilitacion_vencimiento: date | None = None
    tarjeta_unica_circulacion: str | None = None


class TractoUpdateRequest(BaseModel):
    marca: str | None = None
    modelo: str | None = None
    largo_m: float | None = None
    ancho_m: float | None = None
    alto_m: float | None = None
    configuracion_vehicular: str | None = None
    numero_ejes: int | None = None
    tara_kg: float | None = None
    peso_bruto_max_kg: float | None = None
    kilometraje_actual: int | None = None
    estado: EstadoVehiculo | None = None
    soat_vencimiento: date | None = None
    citv_vencimiento: date | None = None
    mtc_habilitacion_vencimiento: date | None = None
    tarjeta_unica_circulacion: str | None = None


class TractoResponse(BaseModel):
    id: uuid.UUID
    placa: str
    marca: str
    modelo: str | None
    anio_fabricacion: int | None
    largo_m: float
    ancho_m: float
    alto_m: float
    configuracion_vehicular: str
    numero_ejes: int | None
    tara_kg: float | None
    peso_bruto_max_kg: float
    kilometraje_actual: int
    estado: EstadoVehiculo
    soat_vencimiento: date | None
    citv_vencimiento: date | None
    mtc_habilitacion_vencimiento: date | None
    tarjeta_unica_circulacion: str | None

    model_config = {"from_attributes": True}


class CarretaCreateRequest(BaseModel):
    placa: str = Field(min_length=6, max_length=10)
    tipo_carreta: TipoCarreta
    marca: str | None = None
    modelo: str | None = None
    anio_fabricacion: int | None = None
    largo_m: float
    ancho_m: float
    alto_m: float
    configuracion_vehicular: str
    numero_ejes: int | None = None
    tara_kg: float | None = None
    peso_bruto_max_kg: float
    kilometraje_actual: int = 0
    soat_vencimiento: date | None = None
    citv_vencimiento: date | None = None
    mtc_habilitacion_vencimiento: date | None = None
    tarjeta_unica_circulacion: str | None = None


class CarretaUpdateRequest(BaseModel):
    tipo_carreta: TipoCarreta | None = None
    marca: str | None = None
    modelo: str | None = None
    largo_m: float | None = None
    ancho_m: float | None = None
    alto_m: float | None = None
    configuracion_vehicular: str | None = None
    numero_ejes: int | None = None
    tara_kg: float | None = None
    peso_bruto_max_kg: float | None = None
    kilometraje_actual: int | None = None
    estado: EstadoVehiculo | None = None
    soat_vencimiento: date | None = None
    citv_vencimiento: date | None = None
    mtc_habilitacion_vencimiento: date | None = None
    tarjeta_unica_circulacion: str | None = None


class CarretaResponse(BaseModel):
    id: uuid.UUID
    placa: str
    tipo_carreta: TipoCarreta
    marca: str | None
    modelo: str | None
    anio_fabricacion: int | None
    largo_m: float
    ancho_m: float
    alto_m: float
    configuracion_vehicular: str
    numero_ejes: int | None
    tara_kg: float | None
    peso_bruto_max_kg: float
    kilometraje_actual: int
    estado: EstadoVehiculo
    soat_vencimiento: date | None
    citv_vencimiento: date | None
    mtc_habilitacion_vencimiento: date | None
    tarjeta_unica_circulacion: str | None

    model_config = {"from_attributes": True}


class MantenimientoCreateRequest(BaseModel):
    tipo_mantenimiento: TipoMantenimiento
    descripcion: str
    kilometraje_actual_registro: int
    kilometraje_proximo: int | None = None
    fecha_realizado: date
    costo: float | None = None
    proveedor: str | None = None
    completado: bool = True


class MantenimientoResponse(BaseModel):
    id: uuid.UUID
    tracto_id: uuid.UUID | None
    carreta_id: uuid.UUID | None
    tipo_mantenimiento: TipoMantenimiento
    descripcion: str
    kilometraje_actual_registro: int
    kilometraje_proximo: int | None
    fecha_realizado: date
    costo: float | None
    proveedor: str | None
    completado: bool

    model_config = {"from_attributes": True}


class AlertaVencimientoResponse(BaseModel):
    entidad_tipo: str
    entidad_id: str
    identificador: str
    concepto: str
    fecha_vencimiento: date
    dias_restantes: int
    vencido: bool
