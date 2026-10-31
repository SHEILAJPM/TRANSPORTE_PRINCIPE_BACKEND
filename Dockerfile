# Debian fijo (bookworm): con el tag genérico la base cambió a trixie y renombró paquetes.
FROM python:3.12-slim-bookworm

# Librerías de sistema que necesita WeasyPrint para generar los PDF.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Aplica las migraciones pendientes y arranca en el puerto que asigna la plataforma
# (Render define PORT; en local se usa 8000).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
