from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "pdf"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)


class MotorPdfNoDisponibleError(Exception):
    """WeasyPrint requiere Pango/GDK-Pixbuf/GObject a nivel de sistema operativo
    (ya instalados en el Dockerfile para Linux); si no están presentes —típicamente
    al correr `uvicorn` directo en Windows sin Docker— falla recién al generar un PDF,
    no al arrancar la aplicación completa.
    """


def renderizar_html(nombre_plantilla: str, contexto: dict[str, Any]) -> str:
    return _env.get_template(nombre_plantilla).render(**contexto)


def renderizar_pdf(nombre_plantilla: str, contexto: dict[str, Any]) -> bytes:
    """Renderiza una plantilla Jinja2 (cotizacion.html, factura.html, guia_remision.html,
    constancia_pesos_medidas.html) a PDF, incluyendo el logo dinámico de la Empresa.
    """
    html = renderizar_html(nombre_plantilla, contexto)

    try:
        from weasyprint import HTML  # import perezoso: ver MotorPdfNoDisponibleError
    except OSError as error:
        raise MotorPdfNoDisponibleError(
            "El motor de generación de PDF (WeasyPrint) no encontró sus dependencias del "
            "sistema (Pango/GDK-Pixbuf/GObject). Disponible al correr vía Docker "
            "(docker compose up); en Windows sin Docker, instala el runtime de GTK3."
        ) from error

    return HTML(string=html, base_url=str(_TEMPLATES_DIR)).write_pdf()
