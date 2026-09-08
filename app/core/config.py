from functools import lru_cache

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
