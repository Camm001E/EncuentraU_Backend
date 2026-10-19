"""Small deterministic field representations; no service or provider imports."""

import re
import unicodedata
from dataclasses import dataclass

from app.domain.matching_vocabulary import (
    ADJECTIVES,
    COLOURS,
    COMPONENTS,
    DISTINCTIVE_HEADS,
    GENERIC,
    GEOMETRY,
    HEADS,
    MATERIALS,
    NUMBERS,
    REPORT_WORDS,
    SHADES,
    STOPWORDS,
    SYNONYMS,
    UNKNOWN,
)


def normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "").casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return "" if text in UNKNOWN else text


def _inflection(value: str) -> str:
    known = COLOURS | HEADS | ADJECTIVES | set(SYNONYMS) | set(GEOMETRY)
    if value.endswith("es") and value[:-2] in known:
        value = value[:-2]
    elif len(value) > 4 and value.endswith("ces"):
        value = value[:-3] + "z"
    elif (
        len(value) > 4 and value.endswith("es") and not value.endswith(("ales", "ores"))
    ):
        candidate = value[:-2]
        value = (
            candidate
            if candidate in COLOURS | HEADS or value.endswith(("ones", "res"))
            else value[:-1]
        )
    elif len(value) > 3 and value.endswith("s"):
        value = value[:-1]
    if value.endswith("a") and value[:-1] + "o" in ADJECTIVES:
        value = value[:-1] + "o"
    return value


def word(value: str) -> str:
    value = _inflection(value)
    value = SYNONYMS.get(value, value)
    return GEOMETRY.get(value, value)


def words(value: str | None) -> list[str]:
    return [word(w) for w in normalize(value).split()]


def tokens(value: str | None) -> frozenset[str]:
    return frozenset(w for w in words(value) if w not in STOPWORDS)


def geometry(value: str | None) -> frozenset[str]:
    return frozenset(GEOMETRY[w] for w in tokens(value) if w in GEOMETRY)


def colour(value: str | None) -> frozenset[str]:
    # Retain unknown colour words for exact, non-dictionary input compatibility.
    return tokens(value) - SHADES


@dataclass(frozen=True)
class Feature:
    head: str
    attributes: frozenset[str]
    colours: frozenset[str]
    quantities: frozenset[str]
    regions: frozenset[str]
    absent: bool = False

    @property
    def information(self) -> int:
        # Distinctive observations with attributes carry more information than
        # generic components; repeated words never add information.
        return (
            1
            + len(self.colours | self.quantities)
            + int(self.head in DISTINCTIVE_HEADS)
        )


def feature(value: str, excluded: frozenset[str] = frozenset()) -> Feature | None:
    sequence = words(value)
    useful = set(sequence) - STOPWORDS - REPORT_WORDS
    if not useful:
        return None
    specific = [w for w in sequence if w in DISTINCTIVE_HEADS]
    heads = specific or [w for w in sequence if w in HEADS]
    head = heads[0] if heads else "lexical"
    colours = frozenset(useful & COLOURS)
    quantities = frozenset(
        NUMBERS.get(w, w) for w in sequence if w in NUMBERS or w.isdecimal()
    )
    regions = set()
    for i, item in enumerate(sequence):
        if (
            item in COMPONENTS | {"esquina", "borde"}
            and item != head
            and any(
                w in {"en", "sobre", "cerca", "alrededor"}
                for w in sequence[max(0, i - 3) : i]
            )
        ):
            regions.add(item)
    attributes = (
        useful - {head} - GENERIC - set(regions) - set(quantities) - {"sin", "no"}
    )
    attributes = {w for w in attributes if w not in NUMBERS}
    if head == "lexical":
        attributes -= excluded
    if (
        head in {"lexical", "pieza", "decoracion", "linea"}
        and not (attributes - COLOURS - MATERIALS)
        and not regions
    ):
        return None
    return Feature(
        head,
        frozenset(attributes),
        colours,
        quantities,
        frozenset(regions),
        "sin" in sequence or "no" in sequence,
    )


def features(
    values: list[str], excluded: frozenset[str] = frozenset()
) -> frozenset[Feature]:
    return frozenset(
        f for value in values if (f := feature(value, excluded)) is not None
    )


def description_features(
    value: str | None, excluded: frozenset[str]
) -> frozenset[Feature]:
    value = re.sub(
        r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", value or ""
    )
    observations = [
        (canonical, _inflection(raw) in ADJECTIVES)
        for raw in normalize(value).split()
        if (canonical := word(raw)) not in excluded | REPORT_WORDS
    ]
    sequence = [canonical for canonical, _ in observations]
    starts = []
    for i, item in enumerate(sequence):
        if item not in HEADS:
            continue
        if any(
            w in {"en", "sobre", "cerca", "alrededor"}
            for w in sequence[max(0, i - 2) : i]
        ):
            continue
        # An adjective remains an attribute of the current observation, even
        # when its synonym is a noun (e.g. damaged -> damage, sewn -> stitch).
        if starts and observations[i][1]:
            continue
        start = i - 1 if i and sequence[i - 1] in NUMBERS else i
        starts.append(start)
    if not starts:
        return features([" ".join(sequence)])
    starts.append(len(sequence))
    return features(
        [" ".join(sequence[a:b]) for a, b in zip(starts, starts[1:], strict=False)]
    )


def literal_text(values: list[str]) -> frozenset[str]:
    return frozenset(
        " ".join(unicodedata.normalize("NFKC", v).casefold().split())
        for v in values
        if normalize(v)
    )
