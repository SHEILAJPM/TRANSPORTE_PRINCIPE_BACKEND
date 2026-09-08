from pydantic import BaseModel


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
