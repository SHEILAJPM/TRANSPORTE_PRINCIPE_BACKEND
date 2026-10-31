import os
import sys
from pathlib import Path

# Las pruebas no deben depender de un .env real: valores mínimos para que Settings cargue.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://prueba:prueba@localhost:5432/prueba")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://prueba:prueba@localhost:5432/prueba")
os.environ.setdefault("SECRET_KEY", "clave-de-prueba")
os.environ.setdefault("APISUNAT_TOKEN", "token-de-prueba")
os.environ.setdefault("DECOLECTA_TOKEN", "token-de-prueba")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
