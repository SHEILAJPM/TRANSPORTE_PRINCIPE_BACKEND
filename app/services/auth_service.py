from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generar_password_hash, verificar_password
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.usuario import Usuario


class CredencialesInvalidasError(Exception):
    pass


class DatosEmpresaFaltantesError(Exception):
    """No hay empresa registrada y no se indicó RUC/razón social para crearla."""


@dataclass
class ResultadoAdmin:
    empresa: Empresa
    admin: Usuario
    empresa_creada: bool
    admin_creado: bool


async def crear_o_restablecer_admin(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    nombres: str | None = None,
    apellidos: str | None = None,
    ruc: str | None = None,
    razon_social: str | None = None,
) -> ResultadoAdmin:
    """El sistema es de una sola empresa de transporte y no tiene registro público:
    el primer administrador se crea con `python -m app.crear_admin`. Si el correo ya
    existe, se le asigna la nueva contraseña y el rol ADMIN (sirve para recuperar el
    acceso). Los demás usuarios los crea el administrador desde /usuarios."""
    empresa = (await db.execute(select(Empresa).limit(1))).scalar_one_or_none()
    empresa_creada = False
    if empresa is None:
        if not ruc or not razon_social:
            raise DatosEmpresaFaltantesError("No hay empresa registrada: indica el RUC y la razón social")
        empresa = Empresa(ruc=ruc, razon_social=razon_social)
        db.add(empresa)
        await db.flush()
        empresa_creada = True

    admin = (await db.execute(select(Usuario).where(Usuario.email == email))).scalar_one_or_none()
    admin_creado = admin is None
    if admin is None:
        admin = Usuario(
            empresa_id=empresa.id,
            nombres=nombres or "Administrador",
            apellidos=apellidos or "",
            email=email,
            hashed_password=generar_password_hash(password),
            rol=RolUsuario.ADMIN,
            activo=True,
        )
        db.add(admin)
    else:
        admin.hashed_password = generar_password_hash(password)
        admin.rol = RolUsuario.ADMIN
        admin.activo = True
    await db.flush()

    return ResultadoAdmin(empresa=empresa, admin=admin, empresa_creada=empresa_creada, admin_creado=admin_creado)


async def autenticar_usuario(db: AsyncSession, email: str, password: str) -> Usuario:
    usuario = (await db.execute(select(Usuario).where(Usuario.email == email))).scalar_one_or_none()
    if usuario is None or not usuario.activo or not verificar_password(password, usuario.hashed_password):
        raise CredencialesInvalidasError("Correo o contraseña incorrectos")
    return usuario
