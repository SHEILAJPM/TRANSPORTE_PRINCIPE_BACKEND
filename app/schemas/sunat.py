from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.cliente import ClienteResponse
from app.schemas.comprobante import BienGuia


class RucConsultaResponse(BaseModel):
    numero_documento: str
    razon_social: str
    nombre_comercial: str | None = None
    estado: str | None = None  # ACTIVO / BAJA DE OFICIO / etc.
    condicion: str | None = None  # HABIDO / NO HABIDO
    direccion: str | None = None
    distrito: str | None = None
    provincia: str | None = None
    departamento: str | None = None
    ubigeo: str | None = None


class DniConsultaResponse(BaseModel):
    numero_documento: str
    nombres: str
    apellido_paterno: str
    apellido_materno: str

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellido_paterno} {self.apellido_materno}".strip()


class ParteGuia(BaseModel):
    tipo_documento: str  # Catálogo 06: "6" RUC, "1" DNI
    numero_documento: str
    razon_social: str


class PuntoGuia(BaseModel):
    ubigeo: str | None
    direccion: str | None


class ConsultaGuiaRemitenteRequest(BaseModel):
    ruc: str = Field(pattern=r"^\d{11}$", description="RUC del cliente que emitió la guía")
    serie: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9]{3}$")
    numero: str = Field(pattern=r"^\d{1,8}$")


class GuiaRemitenteTextoRequest(BaseModel):
    texto: str = Field(min_length=40, max_length=50_000, description="Detalle de GRE copiado desde SUNAT SOL")


class GuiaRemitenteImportadaResponse(BaseModel):
    """Borrador del viaje armado desde la guía de remitente del cliente. No crea el
    viaje: el frontend lo completa con tracto y chofer y lo envía a /viajes/activar."""

    cliente: ClienteResponse
    remitente_guia_ruc_emisor: str
    remitente_guia_serie: str
    remitente_guia_numero: str
    fecha_emision_guia: date | None
    destinatario: ParteGuia | None
    origen: PuntoGuia
    destino: PuntoGuia
    peso_tm: float | None
    numero_bultos: int | None
    fecha_inicio_traslado: date | None
    motivo_traslado: str | None
    bienes: list[BienGuia]
    advertencias: list[str]


class ConexionResponse(BaseModel):
    clave: str  # certificado | credenciales_gre | credenciales_sol | facturas
    nombre: str
    lista: bool
    detalle: str


class CertificadoEstadoResponse(BaseModel):
    """Estado del certificado digital .p12 y de cada conexión con SUNAT (nunca expone
    claves ni contraseñas)."""

    listo_para_firmar: bool
    mensaje: str
    titular: str | None = None
    vence_en: datetime | None = None
    dias_para_vencer: int | None = None
    conexiones: list[ConexionResponse] = []


class PruebaConexionResponse(BaseModel):
    ok: bool
    mensaje: str
    conexiones: list[ConexionResponse]
