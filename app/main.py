import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.services.sunat_certificado_service import CertificadoSunatError, cargar_certificado

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Un certificado faltante o inválido no debe impedir que el backend arranque:
    # solo se avisa, y las operaciones que firman responden con un error claro.
    if settings.GRE_PROVEEDOR == "sunat_directo":
        try:
            cargar_certificado()
        except CertificadoSunatError as error:
            logger.warning("Certificado digital SUNAT no disponible: %s", error)
    yield


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(CertificadoSunatError)
async def certificado_sunat_error_handler(request: Request, error: CertificadoSunatError):
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(error)})


if settings.STORAGE_BACKEND == "local":
    # Sirve el logotipo de la empresa y demás adjuntos guardados localmente
    # (en producción, STORAGE_BACKEND=s3 los sirve directamente desde el bucket).
    Path(settings.STORAGE_LOCAL_PATH).mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=settings.STORAGE_LOCAL_PATH), name="static")


@app.get("/health", tags=["Sistema"])
async def health_check():
    return {"status": "ok", "servicio": settings.PROJECT_NAME}
