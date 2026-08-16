from __future__ import annotations

from collections.abc import Mapping

from .boolean_parser import normalize_text


# La agencia no es un agregador generalista: cada pieza debe pertenecer a una
# mesa editorial verificable. Salud sólo ingresa cuando tiene impacto público,
# regulatorio, presupuestario o institucional.
EDITORIAL_DESKS: dict[str, tuple[str, ...]] = {
    "Legislatura bonaerense": (
        "legislatura bonaerense", "senado bonaerense", "diputados bonaerenses",
        "camara de diputados de la provincia", "camara de senadores de la provincia",
        "legislatura de la provincia de buenos aires", "hcdiputados-ba", "senado-ba",
    ),
    "Congreso nacional": (
        "congreso nacional", "senado de la nacion", "camara de diputados de la nacion",
        "hcdn", "senado.gob.ar", "proyecto de ley", "comision legislativa",
    ),
    "Ejecutivo y politica": (
        "gobierno", "presidente", "gobernador", "ministerio", "intendente", "eleccion",
        "elecciones", "partido politico", "ucr", "pro", "pj", "peron", "libertad avanza",
        "decreto", "resolucion", "boletin oficial", "gabinete",
    ),
    "Economia y regulacion": (
        "economia", "dolar", "inflacion", "presupuesto", "bcra", "indec", "afip",
        "impuesto", "mercado", "licitacion", "contratacion", "adjudicacion", "regulacion",
        "tarifa", "energia", "exportacion", "tesoro", "financiamiento",
    ),
    "Salud, politica y presupuesto": (
        "pami", "ioma", "anmat", "ministerio de salud", "obra social", "hospital",
        "medicamento", "vacuna", "salud publica", "sistema de salud", "prestacion",
    ),
}

HEALTH_PUBLIC_IMPACT = (
    "presupuesto", "financiamiento", "licitacion", "contratacion", "compra", "medicamento",
    "anmat", "pami", "ioma", "obra social", "resolucion", "decreto", "proyecto", "ley",
    "regulacion", "cobertura", "hospital publico",
)


def editorial_text(item: Mapping[str, object] | object) -> str:
    if isinstance(item, Mapping):
        values = (item.get("title", ""), item.get("subtitle", ""), item.get("summary", ""), item.get("source", ""), item.get("domain", ""))
    else:
        values = tuple(getattr(item, key, "") for key in ("title", "subtitle", "summary", "source", "domain"))
    return normalize_text(" ".join(str(value or "") for value in values))


def classify_editorial_desk(item: Mapping[str, object] | object) -> str:
    text = editorial_text(item)
    matched = [desk for desk, markers in EDITORIAL_DESKS.items() if any(marker in text for marker in markers)]
    if "Salud, politica y presupuesto" in matched and not any(marker in text for marker in HEALTH_PUBLIC_IMPACT):
        matched.remove("Salud, politica y presupuesto")
    # Legislatura y Congreso son las mesas de mayor especificidad.
    for desk in ("Legislatura bonaerense", "Congreso nacional", "Salud, politica y presupuesto", "Economia y regulacion", "Ejecutivo y politica"):
        if desk in matched:
            return desk
    return ""


def is_editorially_in_scope(item: Mapping[str, object] | object) -> bool:
    return bool(classify_editorial_desk(item))
