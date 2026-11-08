"""UBIGEO (INEI) a partir de nombres: "LIMA - LIMA - ANCON" -> "150102".

Las guías que se leen como texto (PDF o el "Detalle de GRE" copiado de SOL) traen el
departamento, provincia y distrito al final de la dirección, pero no el código.
Tabla de app/data/ubigeo_inei.json (paquete ubigeo-fns, licencia MIT).
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_RUTA = Path(__file__).resolve().parent.parent / "data" / "ubigeo_inei.json"


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", sin_tildes.upper()).strip()


@lru_cache(maxsize=1)
def _tabla() -> list[tuple[str, str, str, str]]:
    filas = json.loads(_RUTA.read_text(encoding="utf-8"))
    return [(u, _normalizar(dep), _normalizar(prov), _normalizar(dist)) for u, dep, prov, dist in filas]


def buscar_ubigeo(departamento: str, provincia: str, distrito: str) -> str | None:
    dep, prov, dist = _normalizar(departamento), _normalizar(provincia), _normalizar(distrito)
    exactos = [u for u, d, p, di in _tabla() if d == dep and p == prov and di == dist]
    if len(exactos) == 1:
        return exactos[0]
    # La provincia a veces se escribe distinto (p.ej. "PROV. CONST. DEL CALLAO").
    por_distrito = [u for u, d, _, di in _tabla() if d == dep and di == dist]
    return por_distrito[0] if len(por_distrito) == 1 else None


def separar_ubigeo_de_direccion(direccion: str) -> tuple[str, str | None]:
    """Si la dirección termina en "DEPARTAMENTO - PROVINCIA - DISTRITO" y esos nombres
    existen, devuelve (dirección sin esa cola, ubigeo); si no, (dirección, None)."""
    partes = re.split(r"\s+[-–]\s+", direccion.strip())
    if len(partes) < 3:
        return direccion.strip(), None
    # El departamento viene pegado al final de la dirección ("... TELESUP) LIMA") y puede
    # tener varias palabras ("MADRE DE DIOS"): se prueban las últimas 1 a 3 palabras.
    palabras = partes[-3].split()
    candidatos = [(" ".join(palabras[:-n]), " ".join(palabras[-n:])) for n in range(1, min(3, len(palabras)) + 1)]
    for resto, departamento in candidatos:
        ubigeo = buscar_ubigeo(departamento, partes[-2], partes[-1])
        if ubigeo:
            direccion_limpia = " - ".join([*partes[:-3], resto] if resto else partes[:-3]).strip(" -–,")
            return direccion_limpia or direccion.strip(), ubigeo
    return direccion.strip(), None
