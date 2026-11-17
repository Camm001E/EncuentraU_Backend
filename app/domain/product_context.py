"""Product/container descriptions can retrieve candidates, never certify identity."""

from dataclasses import dataclass

from app.domain.semantic_normalization import tokens

CONTAINERS = frozenset(
    "botella envase frasco bote tubo tarro recipiente dispensador dispensadora".split()
)
FAMILIES = {
    "cleanser": {"jabon", "limpiador", "limpiadora"},
    "shampoo": {"shampoo", "champu"},
    "conditioner": {"acondicionador"},
    "cream": {"crema", "locion", "hidratante"},
    "perfume": {"perfume", "colonia"},
    "toothpaste": {"dentifrico"},
    "deodorant": {"desodorante"},
    "sunscreen": {"bloqueador"},
}


@dataclass(frozen=True)
class ProductContext:
    bridge: bool = False
    conflict: bool = False


def _families(words):
    result = {name for name, vocabulary in FAMILIES.items() if words & vocabulary}
    if {"pasta", "dental"} <= words:
        result.add("toothpaste")
    if {"protector", "solar"} <= words:
        result.add("sunscreen")
    # Moisturizing sunscreen stays sunscreen; other mixed purposes are ambiguous.
    if "sunscreen" in result:
        result.discard("cream")
    return result


def compare_product_context(left, right):
    types = [tokens(obj.object_type) for obj in (left, right)]
    if not any(words & CONTAINERS for words in types):
        return ProductContext()
    named = [_families(words) for words in types]
    if all(len(family) == 1 for family in named) and named[0] != named[1]:
        return ProductContext(conflict=True)
    evidence = [
        words | tokens(obj.description)
        for words, obj in zip(types, (left, right), strict=True)
    ]
    families = [_families(words) for words in evidence]
    if not all(len(family) == 1 for family in families):
        return ProductContext()
    if families[0] != families[1]:
        return ProductContext(conflict=True)
    if any(words & {"no", "sin"} for words in evidence):
        return ProductContext()
    solid = {"barra", "pastilla"}
    fluid = {"liquido", "liquida", "gel", "espuma"}
    if any(a & solid and b & fluid for a, b in (evidence, evidence[::-1])):
        return ProductContext(conflict=True)
    # Different stated applications must not be merged just because both are soap.
    uses = []
    for words in evidence:
        uses.append(
            {
                name
                for name, vocabulary in {
                    "face": {"facial", "cara", "rostro"},
                    "hands": {"mano"},
                    "body": {"corporal", "cuerpo"},
                    "dishes": {"plato", "vajilla"},
                    "clothes": {"ropa"},
                }.items()
                if words & vocabulary
            }
        )
    if uses[0] and uses[1] and not uses[0] & uses[1]:
        return ProductContext(conflict=True)
    # Each title must name either the packaging or a product. Descriptions of
    # unrelated objects mentioning a product cannot activate this bridge.
    grounded = all(words & CONTAINERS or _families(words) for words in types)
    return ProductContext(bridge=grounded)
