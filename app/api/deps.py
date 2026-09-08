import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decodificar_access_token
from app.models.enums import RolUsuario
from app.models.usuario import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> Usuario:
    credenciales_invalidas = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas o token vencido",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decodificar_access_token(token)
        usuario_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise credenciales_invalidas

    usuario = await db.get(Usuario, usuario_id)
    if usuario is None or not usuario.activo:
        raise credenciales_invalidas
    return usuario


def require_roles(*roles_permitidos: RolUsuario) -> Callable[..., Coroutine[Any, Any, Usuario]]:
    """Restringe un endpoint a los roles indicados (p.ej. `require_roles(RolUsuario.ADMIN)`)."""

    async def dependencia(usuario_actual: Usuario = Depends(get_current_user)) -> Usuario:
        if usuario_actual.rol not in roles_permitidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos suficientes para realizar esta acción",
            )
        return usuario_actual

    return dependencia
