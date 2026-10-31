from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings


class ArchivoPrivadoNoEncontradoError(Exception):
    """El archivo privado solicitado no existe en el almacenamiento."""


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

    def guardar_privado(self, clave: str, contenido: bytes, content_type: str) -> str:
        """Guarda un archivo que NO debe quedar accesible por URL pública (XML firmado,
        CDR). Devuelve la clave con la que luego se lee mediante `leer_privado`."""
        if settings.STORAGE_BACKEND == "s3":
            self._cliente_s3().put_object(
                Bucket=settings.S3_BUCKET_NAME, Key=f"privado/{clave}", Body=contenido, ContentType=content_type
            )
            return clave
        destino = Path(settings.STORAGE_PRIVADO_LOCAL_PATH) / clave
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
        return clave

    def leer_privado(self, clave: str) -> bytes:
        if settings.STORAGE_BACKEND == "s3":
            cliente = self._cliente_s3()
            try:
                return cliente.get_object(Bucket=settings.S3_BUCKET_NAME, Key=f"privado/{clave}")["Body"].read()
            except cliente.exceptions.NoSuchKey as error:
                raise ArchivoPrivadoNoEncontradoError(clave) from error
        base = Path(settings.STORAGE_PRIVADO_LOCAL_PATH).resolve()
        ruta = (base / clave).resolve()
        if base not in ruta.parents or not ruta.is_file():
            raise ArchivoPrivadoNoEncontradoError(clave)
        return ruta.read_bytes()

    def _guardar_local(self, clave: str, contenido: bytes) -> str:
        destino = Path(settings.STORAGE_LOCAL_PATH) / clave
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
        return f"/static/{clave}"

    def _guardar_s3(self, clave: str, contenido: bytes, content_type: str | None) -> str:
        self._cliente_s3().put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=clave,
            Body=contenido,
            ContentType=content_type or "application/octet-stream",
        )
        return f"https://{settings.S3_BUCKET_NAME}.s3.{settings.S3_REGION}.amazonaws.com/{clave}"

    def _cliente_s3(self):
        import boto3

        return boto3.client(
            "s3",
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        )
