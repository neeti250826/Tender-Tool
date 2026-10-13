"""Buyer segment for a tender buyer, and whether a tagged line is in scope for that buyer."""
import re

from tagger import SEG, norm

SEGMENTS = [
    ("Non-clinical lab (environment / food / energy / regulator)",
     r"energia electrica|\benee\b|\bcree\b|comision reguladora de energia|recursos naturales|ambiente|\bserna\b|cescco|agricultura|ganaderia"
     r"|\bsag\b|senasa|\bcafe\b|acueductos|\banda\b|aguas de|\bsanaa\b|alimentos|regulacion sanitaria|\barsa\b|superintendencia de regulacion"
     r"|\bmarn\b|\bcenta\b|investigaciones agropecuarias|hidroelectrica|\bcel\b|geotermica"),
    ("Social security", r"\bisss\b|\bihss\b|seguro social|seguridad social"),
    ("Blood bank", r"cruz roja|banco de sangre|programa nacional de sangre|centro nacional de sangre|hemocentro"),
    ("Reference / public-health lab", r"laboratorio nacional|laboratorio central|vigilancia de la salud|laboratorio de referencia|\blnv\b|\blcr\b"),
    ("Military / police health", r"militar|defensa|sedena|cosam|fuerza (aerea|naval|armada)|fuerzas armadas|ejercito|policia|\bpnc\b|cefafa"),
    ("Forensic / justice", r"ministerio publico|medicina forense|medicina legal|fiscalia|corte suprema|poder judicial|judicatura|centros? penal|penitenciari"
                           r"|menores infractores|ministerio de (justicia y )?seguridad"),
    ("Academic / research", r"universidad|\bunah\b|\bues\b|unicaes|instituto de investigacion|consejo .*ciencia"),
    ("Public hospital", r"hospital"),
    ("Ministry of Health (central / regional / primary care)",
     r"secretaria (de estado en el despacho )?de salud|\bsesal\b|\bminsal\b|ministerio de salud|region(al)? (departamental|metropolitana|de salud|sanitaria)"
     r"|fosalud|fondo solidario para la salud|\bucsf\b|primer nivel|establecimientos? de salud|direccion regional de salud|sibasi"),
    ("Other public health body",
     r"salud|bienestar magisterial|\bisbm\b|\bisri\b|rehabilitacion|bomberos|copeco|contingencias|proteccion civil|emergencias medicas|dsem|conapina|ccssp|consejo superior de salud"),
]
SEGMENTS = [(n, re.compile(p)) for n, p in SEGMENTS]
LIMITED = {"Non-clinical lab (environment / food / energy / regulator)", "Other public (non-health)"}


def segment(buyer):
    b = norm(buyer)
    for name, rx in SEGMENTS:
        if rx.search(b):
            return name
    return "Other public (non-health)"


def in_scope(seg, code):
    """Non-health / non-clinical buyers: keep only point-of-care tests and diabetes supplies."""
    if seg not in LIMITED:
        return True
    return SEG[code].split(".")[0] in ("2", "6")
