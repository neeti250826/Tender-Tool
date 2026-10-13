"""Edge-case regression checks for tagger.tag (item, expected code or None)."""
from tagger import tag

CASES = [
    ("Reactivo PCR latex", "41116004", "IACRP"),
    ("Prueba rapida VIH 1/2 cassette", "41116010", "PHIVS"),
    ("KIT RT-PCR SARS-COV-2 tiempo real", "", "MCOVL"),
    ("Tiras reactivas para orina 10 parametros", "41116004", "URQUA"),
    ("Insulina NPH 100 UI/ml frasco", "51183603", None),
    ("Glucosa enzimatica reactivo 4x125 ml", "41116004", "CCROU"),
    ("Antisuero anti A", "41116002", "BGNTZ"),
    ("FRASCO ANTI D", "41116002", "BGNTZ"),
    ("Hematoxilina de Harris 1 litro", "", "HNERM"),
    ("Cartuchos Xpert MTB/RIF", "", "MTBPZ"),
    ("Dextrosa al 5% solucion inyectable", "51191905", None),
    ("Hemoglobina glicosilada HbA1c Afinion cartucho", "", "POCHZ"),
    ("Agar sangre deshidratado 500 g", "41116011", "MIDCL"),
    ("Lancetas esteriles", "41104102", "DBLPU"),
    ("20 GALON ALCOHOL ETILICO, 10 SET SIFILIS TP DETERMINE EN COMBO, 50 UNIDADES PLASTILINA", "", "PSYPH"),
    ("FOCOS DELANTEROS TOYOTA HILUX 2007+ RH ORIGINAL", "39101700", None),
    ("8 galones de diluyente", "31211900", None),
    ("PDA 1: P.A.S.-TINCION ESPECIAL PARA IDENTIFICAR CARBOHIDRATOS", "30222408", "TDXSR"),
    ("DESADUANAJE DE REACTIVOS PARA COVID-19,APO 20-00008448", "24131504", None),
    ("PRUEBA DE ANTIGENO BIOCREDIT COVID-19", "41116010", "PCOVH"),
    ("2 KIT DE JERINGAS DE HIDROXIDO CALCIO", "42151600", None),
    ("diluyente para equipo automatizado en hematologia de 20 litros", "41116008", "HMCBC"),
    ("ESPARADRAPO HOSPITALARIO HIPOALERGENICO A PRUEBA DE AGUA", "42311500", None),
    ("599 KIT DE ALIMENTOS (BASICOS) PARA PERSONAL - COVID-19", "50000000", None),
    ("Tubos tapon Morado Edta 4 ml 12X75", "41105308", None),
    ("TP y TPT reactivo", "41116005", "COTRA"),
    ("Autoclave para esterilizar medios de cultivo bacteriologico", "42281500", None),
    ("TALONARIOS DE RECETARIOS Y SOLICITUD DE EXAMENES DE LABORATORIO", "14111800", None),
]

bad = 0
for text, unspsc, want in CASES:
    got = tag(item=text, buyer="Hospital Santa Barbara", unspsc=unspsc)
    code = got["code"] if got else None
    ok = code == want
    bad += not ok
    print("OK " if ok else "BAD", (text[:58]).ljust(60), "want", want, "got", code, "" if ok else got)
print("failures:", bad)
