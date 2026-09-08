from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generar_password_hash, verificar_password
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.usuario import Usuario


class RucYaRegistradoError(Exception):
    pass


class EmailYaRegistradoError(Exception):
    pass


class CredencialesInvalidasError(Exception):
    pass


async def registrar_empresa_y_admin(
    db: AsyncSession,
    *,
    ruc: str,
    razon_social: str,
    admin_nombres: str,
    admin_apellidos: str,
    admin_email: str,
    admin_password: str,
) -> tuple[Empresa, Usuario]:
    """Alta inicial del sistema: crea la Empresa y su primer Usuario ADMIN en una
    sola transacción. Es el único endpoint de `auth` que no requiere autenticación previa.
    """
    if (await db.execute(select(Empresa).where(Empresa.ruc == ruc))).scalar_one_or_none() is not None:
        raise RucYaRegistradoError(f"Ya existe una empresa registrada con RUC {ruc}")
    if (await db.execute(select(Usuario).where(Usuario.email == admin_email))).scalar_one_or_none() is not None:
        raise EmailYaRegistradoError(f"El correo {admin_email} ya está registrado")

    empresa = Empresa(ruc=ruc, razon_social=razon_social)
    db.add(empresa)
    await db.flush()

    admin = Usuario(
        empresa_id=empresa.id,
        nombres=admin_nombres,
        apellidos=admin_apellidos,
        email=admin_email,
        hashed_password=generar_password_hash(admin_password),
        rol=RolUsuario.ADMIN,
        activo=True,
    )
    db.add(admin)
    await db.flush()

    return empresa, admin


async def autenticar_usuario(db: AsyncSession, email: str, password: str) -> Usuario:
    usuario = (await db.execute(select(Usuario).where(Usuario.email == email))).scalar_one_or_none()
    if usuario is None or not usuario.activo or not verificar_password(password, usuario.hashed_password):
        raise CredencialesInvalidasError("Correo o contraseña incorrectos")
    return usuario
