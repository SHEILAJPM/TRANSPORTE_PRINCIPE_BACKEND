from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(title=settings.PROJECT_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

if settings.STORAGE_BACKEND == "local":
    # Sirve el logotipo de la empresa y demás adjuntos guardados localmente
    # (en producción, STORAGE_BACKEND=s3 los sirve directamente desde el bucket).
    Path(settings.STORAGE_LOCAL_PATH).mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=settings.STORAGE_LOCAL_PATH), name="static")


@app.get("/health", tags=["Sistema"])
async def health_check():
    return {"status": "ok", "servicio": settings.PROJECT_NAME}
