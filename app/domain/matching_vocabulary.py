"""Shared Spanish vocabulary, never conditioned on an object, fixture or colour."""

UNKNOWN = frozenset(
    {
        "desconocido",
        "desconocida",
        "no identificado",
        "no identificada",
        "no visible",
        "no legible",
        "no se distingue",
        "sin marca",
        "n a",
    }
)
STOPWORDS = frozenset(
    "a al con de del el en es la las lo los para por que se su "
    "un una unos unas y o sobre alrededor cerca como forma".split()
)
REPORT_WORDS = frozenset(
    "perdi perdido perdida encontre encontrado encontrada hallado hallada "
    "extraviado extraviada hoy ayer manana dia fecha".split()
)
GENERIC = frozenset(
    "objeto producto parte pieza detalle decorativo decoracion pequeno grande "
    "compacto general visible lateral izquierdo derecho superior inferior nuevo".split()
)
COLOURS = frozenset(
    "negro blanco gris azul rojo verde amarillo naranja violeta morado rosa "
    "marron cafe beige plateado dorado turquesa cian celeste transparente "
    "multicolor".split()
)
MATERIALS = frozenset(
    "plastico metal cuero tela madera vidrio goma silicona aluminio acero".split()
)
SHADES = frozenset({"claro", "oscuro", "pastel", "brillante", "mate"})
GEOMETRY = {
    "circular": "circular",
    "redondo": "circular",
    "esferico": "circular",
    "ovalado": "ovalado",
    "oval": "ovalado",
    "eliptico": "ovalado",
    "rectangular": "rectangular",
    "cuadrado": "rectangular",
    "cilindrico": "cilindrico",
    "curvo": "curvo",
    "arqueado": "curvo",
    "plano": "plano",
    "alargado": "alargado",
    "triangular": "triangular",
    "irregular": "irregular",
}
# Semantic heads identify an observation; locations remain separate attributes.
DISTINCTIVE_HEADS = frozenset(
    {
        "parche",
        "costura",
        "remache",
        "marca",
        "dano",
        "adhesivo",
        "mancha",
        "cierre",
        "llavero",
        "inscripcion",
    }
)
COMPONENTS = frozenset(
    "banda copa almohadilla boton pantalla panel aro bisagra union articulacion "
    "asa tapa base bolsillo cable puerto teclado".split()
)
HEADS = DISTINCTIVE_HEADS | COMPONENTS | {"decoracion", "linea", "pieza"}
NUMBERS = {
    "uno": "1",
    "un": "1",
    "una": "1",
    "dos": "2",
    "doble": "2",
    "tres": "3",
    "triple": "3",
    "cuatro": "4",
    "cinco": "5",
    "seis": "6",
    "siete": "7",
    "ocho": "8",
    "nueve": "9",
    "diez": "10",
}
SYNONYMS = {
    "auricular": "audifono",
    "morral": "mochila",
    "termo": "botella",
    "bluetooth": "inalambrico",
    "inalambrica": "inalambrico",
    "cremallera": "cierre",
    "zipper": "cierre",
    "diadema": "banda",
    "bisagra": "articulacion",
    "union": "articulacion",
    "junta": "articulacion",
    "tecla": "boton",
    "comando": "control",
    "funcion": "control",
    "raspon": "dano",
    "rayon": "dano",
    "aranazo": "dano",
    "desgaste": "dano",
    "roto": "dano",
    "danado": "dano",
    "rotura": "dano",
    "rayado": "dano",
    "simbolo": "marca",
    "logotipo": "marca",
    "logo": "marca",
    "senal": "marca",
    "cosido": "costura",
    "coser": "costura",
    "oblicuo": "diagonal",
    "detalle": "decoracion",
    "decorativo": "decoracion",
    "decorada": "decoracion",
    "metalico": "metal",
    "intraural": "intraural",
    "numerico": "numero",
    "encendido": "control",
    "volumen": "control",
    "ajustable": "ajuste",
    "ajustado": "ajuste",
    "alrededor": "alrededor",
}
# Gender normalization is restricted to known adjectives, not arbitrary nouns.
ADJECTIVES = (
    COLOURS
    | MATERIALS
    | SHADES
    | frozenset(GEOMETRY)
    | {
        "acolchado",
        "cosido",
        "roto",
        "danado",
        "rayado",
        "oblicuo",
        "numerico",
        "cientifico",
        "decorativo",
        "termico",
        "inalambrico",
        "pequeno",
        "grande",
        "compacto",
        "nuevo",
        "metalico",
    }
)
