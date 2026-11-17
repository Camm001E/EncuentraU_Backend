"""Symmetric semantic comparison, independent of scoring policy."""

from dataclasses import dataclass

from app.domain.matching_vocabulary import (
    ADJECTIVES,
    COLOURS,
    DISTINCTIVE_HEADS,
    GENERIC,
    GEOMETRY,
    MATERIALS,
)
from app.domain.semantic_normalization import Feature, literal_text, tokens


def overlap(left: frozenset, right: frozenset) -> float | None:
    if not left or not right:
        return None
    return len(left & right) / min(len(left), len(right))


def object_type_similarity(left: str | None, right: str | None) -> float | None:
    modifiers = GENERIC | ADJECTIVES | set(GEOMETRY.values())
    a, b = tokens(left) - modifiers, tokens(right) - modifiers
    # Wallet terminology varies by provider. Keep this alias scoped to types.
    aliases = {
        "cartera": "billetera",
        "cosmetiquera": "neceser",
        "paraguas": "sombrilla",
        "archivador": "carpeta",
        "archivadores": "carpeta",
        "smartphone": "telefono",
        "smartphones": "telefono",
        "celular": "telefono",
        "movil": "telefono",
        "funda": "estuche",
    }
    # Lookups use normalized tokens, including invariant nouns such as
    # "paraguas" that the general plural rule reduces to "paragua".
    aliases = {
        token: canonical
        for spelling, canonical in aliases.items()
        for token in tokens(spelling)
    }
    a = frozenset(aliases.get(w, w) for w in a)
    b = frozenset(aliases.get(w, w) for w in b)
    # A small zip pouch may be described by its construction instead of its
    # use. Preserve explicit contents/use, and do not generalize bags or totes.
    if {"bolsita", "cierre"} <= a:
        a = (a - {"bolsita", "cierre"}) | {"estuche"}
    if {"bolsita", "cierre"} <= b:
        b = (b - {"bolsita", "cierre"}) | {"estuche"}
    # A generic case can be a pencil case; explicit different uses must not
    # become equivalent (e.g. earphone case versus pencil case).
    if (a == {"estuche"} and bool({"cartuchera", "neceser"} & b)) or (
        b == {"estuche"} and bool({"cartuchera", "neceser"} & a)
    ):
        return 0.8
    return overlap(a, b)


@dataclass(frozen=True)
class Comparison:
    similarity: float | None
    contradictions: tuple[str, ...] = ()


def feature_pair(left: Feature, right: Feature) -> Comparison:
    for absent, present in ((left, right), (right, left)):
        if (
            absent.head == "dano"
            and absent.absent
            and not absent.regions
            and (present.head == "dano" or "dano" in present.attributes)
            and not present.absent
        ):
            return Comparison(
                0.0, ("Se declara ausencia de daños frente a un daño explícito.",)
            )
    generic = {"pieza", "decoracion", "linea", "lexical"}
    shared = left.attributes & right.attributes
    related = (
        left.head == right.head
        or (
            bool({left.head, right.head} & generic)
            and bool(shared - COLOURS - MATERIALS or left.regions & right.regions)
        )
        or ({left.head, right.head} <= {"marca", "dano"} and bool(shared))
    )
    if not related:
        return Comparison(0.0)
    contradictions = []
    if left.colours and right.colours and not left.colours & right.colours:
        contradictions.append("Colores explícitos distintos en un rasgo comparable.")
    if left.quantities and right.quantities and not left.quantities & right.quantities:
        contradictions.append(
            "Cantidades explícitas incompatibles en un rasgo comparable."
        )
    # Proportion (alargado), surface (plano/curvo) and volume (cilindrico)
    # can coexist with a contour. Their lexical difference is not a conflict.
    # Keep similarity unchanged: absence of a contradiction is not agreement.
    contours = {"circular", "ovalado", "rectangular", "triangular"}
    left_geometry = left.attributes & contours
    right_geometry = right.attributes & contours
    if left_geometry and right_geometry and not left_geometry & right_geometry:
        contradictions.append("Geometrías explícitas diferentes en un mismo rasgo.")
    if left.absent != right.absent:
        contradictions.append(
            "Un rasgo está presente en un reporte y negado en el otro."
        )
    if contradictions:
        return Comparison(0.0, tuple(contradictions))
    if left == right and left.head in DISTINCTIVE_HEADS:
        return Comparison(1.0)
    meaningful = (shared - GENERIC) | (left.quantities & right.quantities)
    if left.head == "lexical":
        return Comparison(overlap(left.attributes, right.attributes) or 0.0)
    if meaningful:
        return Comparison(
            overlap(left.attributes, right.attributes)
            if left.attributes and right.attributes
            else 1.0
        )
    # The same component with different unspecified attributes gives only
    # partial support, not a full identity match from its generic name.
    return Comparison(
        0.5 if left.head == right.head and left.attributes and right.attributes else 0.0
    )


def compare_features(left: frozenset[Feature], right: frozenset[Feature]) -> Comparison:
    if not left or not right:
        return Comparison(None)
    contradictions = set()

    def directed(source, target):
        points = 0.0
        for a in source:
            options = [feature_pair(a, b) for b in target]
            best = max(c.similarity or 0 for c in options)
            # Contradictions must have a comparable head; alternatives that
            # explain a feature take precedence over an unrelated clash.
            if best == 0:
                contradictions.update(w for c in options for w in c.contradictions)
            points += a.information * best
        return points / sum(a.information for a in source)

    similarity = (directed(left, right) + directed(right, left)) / 2
    return Comparison(similarity, tuple(sorted(contradictions)))


def compare_visual(
    left, right, left_text: list[str], right_text: list[str]
) -> Comparison:
    comparison = compare_features(left, right)
    a, b = literal_text(left_text), literal_text(right_text)
    if not a or not b:
        return comparison
    text_score = overlap(a, b)
    warnings = set(comparison.contradictions)
    if not a & b:
        warnings.add("El texto visible comparable es diferente.")
    values = [
        value for value in (comparison.similarity, text_score) if value is not None
    ]
    return Comparison(sum(values) / len(values), tuple(sorted(warnings)))
