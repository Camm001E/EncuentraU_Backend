import re
import unicodedata

from app.domain.matching import (
    MatchableObject,
    MatchEvaluation,
    MatchFactor,
    MatchFactorName,
    MatchFactorStatus,
    MatchLevel,
    MatchRequest,
)


class MatchingService:
    """Deterministic evidence scores; percentages are not probabilities."""

    _weights = {
        MatchFactorName.OBJECT_TYPE: 20,
        MatchFactorName.CATEGORY: 10,
        MatchFactorName.COLOR: 12,
        MatchFactorName.BRAND: 12,
        MatchFactorName.VISUAL_FEATURES: 18,
        MatchFactorName.LOCATION: 12,
        MatchFactorName.DATE: 6,
        MatchFactorName.DESCRIPTION: 10,
    }
    _labels = {
        MatchFactorName.OBJECT_TYPE: "Tipo de objeto",
        MatchFactorName.CATEGORY: "Categoría",
        MatchFactorName.COLOR: "Color",
        MatchFactorName.BRAND: "Marca",
        MatchFactorName.VISUAL_FEATURES: "Características visuales",
        MatchFactorName.LOCATION: "Lugar",
        MatchFactorName.DATE: "Fecha",
        MatchFactorName.DESCRIPTION: "Descripción",
    }
    _unknown_values = {
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
    _stopwords = {
        "a",
        "al",
        "con",
        "de",
        "del",
        "el",
        "en",
        "es",
        "la",
        "las",
        "lo",
        "los",
        "para",
        "por",
        "que",
        "se",
        "su",
        "un",
        "una",
        "y",
    }
    _synonyms = {
        "auriculares": "audifonos",
        "auricular": "audifonos",
        "audifono": "audifonos",
        "bluetooth": "inalambricos",
        "inalambrico": "inalambricos",
        "inalambrica": "inalambricos",
        "inalambricas": "inalambricos",
        "negra": "negro",
        "negras": "negro",
        "negros": "negro",
        "blanca": "blanco",
        "blancas": "blanco",
        "blancos": "blanco",
        "roja": "rojo",
        "rojas": "rojo",
        "rojos": "rojo",
        "grises": "gris",
        "azules": "azul",
        "verdes": "verde",
        "amarilla": "amarillo",
        "amarillas": "amarillo",
        "amarillos": "amarillo",
    }

    def evaluate(self, request: MatchRequest) -> MatchEvaluation:
        lost, found = request.lost, request.found
        factors = [
            self._factor(
                MatchFactorName.OBJECT_TYPE,
                self._text_similarity(lost.object_type, found.object_type),
            ),
            self._factor(
                MatchFactorName.CATEGORY,
                self._exact_similarity(lost.category, found.category),
            ),
            self._factor(MatchFactorName.COLOR, self._color_similarity(lost, found)),
            self._factor(
                MatchFactorName.BRAND,
                self._exact_similarity(lost.brand, found.brand),
            ),
            self._factor(
                MatchFactorName.VISUAL_FEATURES,
                self._set_similarity(
                    self._visual_tokens(lost), self._visual_tokens(found)
                ),
            ),
            self._factor(
                MatchFactorName.LOCATION,
                self._text_similarity(lost.location, found.location),
            ),
            self._factor(MatchFactorName.DATE, self._date_similarity(lost, found)),
            self._factor(
                MatchFactorName.DESCRIPTION,
                self._text_similarity(lost.description, found.description),
            ),
        ]
        percentage = round(sum(factor.score for factor in factors))
        warnings = []
        decisive_names = {
            MatchFactorName.OBJECT_TYPE,
            MatchFactorName.CATEGORY,
            MatchFactorName.BRAND,
        }
        conflicts = [
            factor.label
            for factor in factors
            if factor.name in decisive_names
            and factor.status == MatchFactorStatus.DIFFERENT
        ]
        if conflicts:
            warnings.append("Hay diferencias en: " + ", ".join(conflicts) + ".")
        missing = [
            factor.label
            for factor in factors
            if factor.status == MatchFactorStatus.UNKNOWN
        ]
        if missing:
            warnings.append("Faltan datos comparables en: " + ", ".join(missing) + ".")
        reversed_dates = (
            lost.event_date is not None
            and found.event_date is not None
            and found.event_date < lost.event_date
        )
        if reversed_dates:
            warnings.append("La fecha del hallazgo es anterior a la pérdida.")

        type_matches = factors[0].status == MatchFactorStatus.MATCH
        if percentage >= 85 and type_matches and not conflicts and not reversed_dates:
            level = MatchLevel.HIGH
        elif percentage >= 65:
            level = MatchLevel.POSSIBLE
        else:
            level = MatchLevel.LOW
        return MatchEvaluation(
            percentage=percentage, level=level, factors=factors, warnings=warnings
        )

    def _factor(self, name: MatchFactorName, similarity: float | None) -> MatchFactor:
        if similarity is None:
            status = MatchFactorStatus.UNKNOWN
            explanation = (
                "Faltan datos útiles en uno o ambos objetos; no aporta puntos."
            )
        elif similarity == 1:
            status = MatchFactorStatus.MATCH
            explanation = "Los datos coinciden tras normalizar el texto."
        elif similarity == 0:
            status = MatchFactorStatus.DIFFERENT
            explanation = "No hay coincidencia en los datos comparados."
        else:
            status = MatchFactorStatus.PARTIAL
            explanation = f"Coincidencia parcial del {similarity:.0%} en este factor."
        if name == MatchFactorName.DATE and similarity is not None:
            explanation = {
                1.0: "La pérdida y el hallazgo tienen la misma fecha.",
                0.75: "El hallazgo ocurrió entre 1 y 3 días después de la pérdida.",
                0.5: "El hallazgo ocurrió entre 4 y 7 días después de la pérdida.",
                0.25: "El hallazgo ocurrió entre 8 y 14 días después de la pérdida.",
                0.0: "El hallazgo es anterior a la pérdida o supera los 14 días.",
            }[similarity]
        return MatchFactor(
            name=name,
            label=self._labels[name],
            weight=self._weights[name],
            score=round(self._weights[name] * (similarity or 0), 2),
            status=status,
            explanation=explanation,
        )

    @classmethod
    def _normalize(cls, value: str | None) -> str:
        decomposed = unicodedata.normalize("NFKD", value or "").casefold()
        unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
        normalized = re.sub(r"[^a-z0-9]+", " ", unaccented).strip()
        return "" if normalized in cls._unknown_values else normalized

    @classmethod
    def _tokens(cls, value: str | None) -> set[str]:
        return {
            cls._synonyms.get(word, word)
            for word in cls._normalize(value).split()
            if word not in cls._stopwords
        }

    @staticmethod
    def _set_similarity(left: set[str], right: set[str]) -> float | None:
        if not left or not right:
            return None
        return len(left & right) / len(left | right)

    @classmethod
    def _text_similarity(cls, left: str | None, right: str | None) -> float | None:
        return cls._set_similarity(cls._tokens(left), cls._tokens(right))

    @classmethod
    def _exact_similarity(cls, left: str | None, right: str | None) -> float | None:
        normalized_left, normalized_right = cls._normalize(left), cls._normalize(right)
        if not normalized_left or not normalized_right:
            return None
        return float(normalized_left == normalized_right)

    @classmethod
    def _visual_tokens(cls, obj: MatchableObject) -> set[str]:
        values = [obj.shape, *obj.visible_features, *obj.visible_text]
        return {token for value in values for token in cls._tokens(value)}

    @classmethod
    def _color_similarity(
        cls, lost: MatchableObject, found: MatchableObject
    ) -> float | None:
        lost_primary = cls._tokens(lost.primary_color)
        found_primary = cls._tokens(found.primary_color)
        lost_colors = lost_primary | {
            token for color in lost.secondary_colors for token in cls._tokens(color)
        }
        found_colors = found_primary | {
            token for color in found.secondary_colors for token in cls._tokens(color)
        }
        if not lost_colors or not found_colors:
            return None
        if lost_primary and lost_primary == found_primary:
            return 1.0
        return 0.5 if lost_colors & found_colors else 0.0

    @staticmethod
    def _date_similarity(lost: MatchableObject, found: MatchableObject) -> float | None:
        if lost.event_date is None or found.event_date is None:
            return None
        days = (found.event_date - lost.event_date).days
        if days < 0 or days > 14:
            return 0.0
        if days == 0:
            return 1.0
        if days <= 3:
            return 0.75
        if days <= 7:
            return 0.5
        return 0.25
