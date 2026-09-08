from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings


class StorageService:
    """Backend de almacenamiento del logo corporativo y otros adjuntos
    (comprobantes de gasto, fotos de novedades). Local en desarrollo, S3 en producción.
    """

    async def guardar_logo_empresa(self, empresa_id, archivo: UploadFile) -> str:
        extension = Path(archivo.filename or "logo.png").suffix or ".png"
        clave = f"logos/{empresa_id}{extension}"
        contenido = await archivo.read()

        if settings.STORAGE_BACKEND == "s3":
            return self._guardar_s3(clave, contenido, archivo.content_type)
        return self._guardar_local(clave, contenido)

    def _guardar_local(self, clave: str, contenido: bytes) -> str:
        destino = Path(settings.STORAGE_LOCAL_PATH) / clave
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
        return f"/static/{clave}"

    def _guardar_s3(self, clave: str, contenido: bytes, content_type: str | None) -> str:
        import boto3

        cliente = boto3.client(
            "s3",
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        )
        cliente.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=clave,
            Body=contenido,
            ContentType=content_type or "application/octet-stream",
        )
        return f"https://{settings.S3_BUCKET_NAME}.s3.{settings.S3_REGION}.amazonaws.com/{clave}"
