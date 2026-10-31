from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Transporte Príncipe API"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str
    DATABASE_URL_SYNC: str

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    APISUNAT_BASE_URL: str = "https://api.apisunat.pe"
    APISUNAT_TOKEN: str
    APISUNAT_TIMEOUT_SECONDS: int = 10

    # Decolecta: consulta de RUC/DNI (RENIEC/SUNAT) para autocompletar clientes. Es un
    # proveedor distinto de apisunat.pe (que solo emite comprobantes electrónicos).
    DECOLECTA_BASE_URL: str = "https://api.decolecta.com"
    DECOLECTA_TOKEN: str
    DECOLECTA_TIMEOUT_SECONDS: int = 10

    # Emisor de la Guía de Remisión Transportista: "apisunat" (vía apisunat.pe) o
    # "sunat_directo" (XML UBL 2.1 firmado por nosotros y enviado a la API REST de GRE).
    GRE_PROVEEDOR: Literal["apisunat", "sunat_directo"] = "sunat_directo"

    # Certificado digital .p12 para firmar lo que se envía directo a SUNAT. Nunca va
    # en el repositorio: en local apunta a una carpeta propia y en Render al Secret
    # File montado en /etc/secrets/.
    SUNAT_CERT_PATH: str | None = None
    SUNAT_CERT_PASSWORD: SecretStr | None = None

    # API REST de GRE de SUNAT. No existe entorno beta para GRE: todo envío es real,
    # por eso la emisión exige confirmar antes una vista previa.
    SUNAT_GRE_TOKEN_URL: str = "https://api-seguridad.sunat.gob.pe/v1/clientessol"
    SUNAT_GRE_API_URL: str = "https://api-cpe.sunat.gob.pe/v1"
    SUNAT_GRE_CLIENT_ID: str | None = None
    SUNAT_GRE_CLIENT_SECRET: SecretStr | None = None
    SUNAT_SOL_USUARIO: str | None = None  # RUC + usuario SOL secundario, p.ej. 20123456789MODDATOS
    SUNAT_SOL_CLAVE: SecretStr | None = None
    SUNAT_GRE_TIMEOUT_SECONDS: int = 20

    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_PATH: str = "./storage"
    S3_BUCKET_NAME: str | None = None
    S3_REGION: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    ALERTA_DIAS_ANTICIPACION_SOAT: int = 30
    ALERTA_DIAS_ANTICIPACION_CITV: int = 30
    ALERTA_DIAS_ANTICIPACION_MTC: int = 30
    ALERTA_DIAS_ANTICIPACION_LICENCIA: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
