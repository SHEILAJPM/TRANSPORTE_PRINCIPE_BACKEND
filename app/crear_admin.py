"""Crea el administrador del sistema o le restablece la contraseña.

El sistema es de una sola empresa y no tiene registro público. Ejecutar desde la
carpeta del backend (usa la base de datos de DATABASE_URL en .env):

    python -m app.crear_admin --email admin@empresa.pe

Pide la contraseña sin mostrarla. Si todavía no hay empresa registrada, también pide
el RUC y la razón social. Si el correo ya existe, le asigna la nueva contraseña y el
rol ADMIN (sirve para recuperar el acceso).
"""

import argparse
import asyncio
import getpass
import re
import sys

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.empresa import Empresa
from app.services.auth_service import crear_o_restablecer_admin

_RE_RUC = re.compile(r"^\d{11}$")


def _pedir(texto: str, validar=lambda v: bool(v), error: str = "Valor obligatorio") -> str:
    while True:
        valor = input(texto).strip()
        if validar(valor):
            return valor
        print(f"  {error}")


def _pedir_password() -> str:
    while True:
        password = getpass.getpass("Contraseña (mínimo 8 caracteres, no se muestra): ")
        if len(password) < 8:
            print("  Debe tener al menos 8 caracteres")
        elif getpass.getpass("Repite la contraseña: ") != password:
            print("  Las contraseñas no coinciden")
        else:
            return password


async def _main(email: str) -> None:
    async with AsyncSessionLocal() as db:
        hay_empresa = (await db.execute(select(Empresa.id).limit(1))).first() is not None
        ruc = razon_social = None
        if not hay_empresa:
            print("No hay ninguna empresa registrada: se creará ahora.")
            ruc = _pedir("RUC de la empresa: ", lambda v: bool(_RE_RUC.fullmatch(v)), "El RUC debe tener 11 dígitos")
            razon_social = _pedir("Razón social: ")
        nombres = _pedir("Nombres del administrador: ")
        apellidos = _pedir("Apellidos del administrador: ")
        password = _pedir_password()

        resultado = await crear_o_restablecer_admin(
            db,
            email=email,
            password=password,
            nombres=nombres,
            apellidos=apellidos,
            ruc=ruc,
            razon_social=razon_social,
        )
        await db.commit()

    await engine.dispose()
    if resultado.empresa_creada:
        print(f"Empresa creada: {resultado.empresa.razon_social} (RUC {resultado.empresa.ruc})")
    accion = "creado" if resultado.admin_creado else "actualizado (nueva contraseña y rol ADMIN)"
    print(f"Administrador {accion}: {email}. Ya puedes iniciar sesión.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crea el administrador o restablece su contraseña.")
    parser.add_argument("--email", required=True, help="Correo con el que el administrador iniciará sesión")
    argumentos = parser.parse_args()
    if "@" not in argumentos.email:
        sys.exit("El correo no es válido")
    asyncio.run(_main(argumentos.email.strip()))
