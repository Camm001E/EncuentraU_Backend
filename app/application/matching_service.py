import re
import unicodedata

from app.domain.matching import (
    MatchableObject,
    MatchEvaluation,
    MatchFactor,
    MatchFactorGroup,
    MatchFactorName,
    MatchFactorStatus,
    MatchLevel,
    MatchRequest,
)


class MatchingService:
    """Normalize identity and context separately; scores are not probabilities."""

    _identity_share = 0.8
    _context_share = 0.2
    _identity_weights = {
        MatchFactorName.OBJECT_TYPE: 25,
        MatchFactorName.CATEGORY: 5,
        MatchFactorName.COLOR: 15,
        MatchFactorName.BRAND: 10,
        MatchFactorName.SHAPE: 10,
        MatchFactorName.VISUAL_FEATURES: 20,
        MatchFactorName.DESCRIPTION: 15,
    }
    _context_weights = {
        MatchFactorName.LOCATION: 60,
        MatchFactorName.DATE: 40,
    }
    _labels = {
        MatchFactorName.OBJECT_TYPE: "Tipo de objeto",
        MatchFactorName.CATEGORY: "Categoría",
        MatchFactorName.COLOR: "Color",
        MatchFactorName.BRAND: "Marca",
        MatchFactorName.SHAPE: "Forma",
        MatchFactorName.VISUAL_FEATURES: "Rasgos visuales",
        MatchFactorName.DESCRIPTION: "Descripción del objeto",
        MatchFactorName.LOCATION: "Lugar",
        MatchFactorName.DATE: "Fecha",
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
        "unos",
        "unas",
        "y",
    }
    _report_words = {
        "perdi",
        "perdido",
        "perdida",
        "perdidos",
        "perdidas",
        "encontre",
        "encontrado",
        "encontrada",
        "encontrados",
        "encontradas",
        "hallado",
        "hallada",
        "hallados",
        "halladas",
        "extraviado",
        "extraviada",
        "extraviados",
        "extraviadas",
    }
    # Vocabulary normalization only: no object-specific scoring rules.
    _synonyms = {
        "audifonos": "audifono",
        "auricular": "audifono",
        "auriculares": "audifono",
        "bluetooth": "inalambrico",
        "inalambrica": "inalambrico",
        "inalambricos": "inalambrico",
        "inalambricas": "inalambrico",
        "copas": "copa",
        "detalles": "detalle",
        "almohadillas": "almohadilla",
        "acolchada": "acolchado",
        "acolchados": "acolchado",
        "acolchadas": "acolchado",
        "botones": "boton",
        "uniones": "union",
        "circumaurales": "circumaural",
        "intraurales": "intraural",
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
        type_similarity = self._text_similarity(lost.object_type, found.object_type)
        color_similarity, color_weight = self._color_similarity(lost, found)
        location_tokens = self._tokens(lost.location) | self._tokens(found.location)
        factors = [
            self._factor(MatchFactorName.OBJECT_TYPE, type_similarity),
            self._factor(
                MatchFactorName.CATEGORY,
                self._exact_similarity(lost.category, found.category),
            ),
            self._factor(MatchFactorName.COLOR, color_similarity, color_weight),
            self._factor(
                MatchFactorName.BRAND,
                self._exact_similarity(lost.brand, found.brand),
            ),
            self._factor(
                MatchFactorName.SHAPE,
                self._text_similarity(lost.shape, found.shape),
            ),
            self._factor(
                MatchFactorName.VISUAL_FEATURES,
                self._feature_similarity(lost, found),
            ),
            self._factor(
                MatchFactorName.DESCRIPTION,
                self._set_similarity(
                    self._description_tokens(lost.description, location_tokens),
                    self._description_tokens(found.description, location_tokens),
                ),
            ),
            self._factor(
                MatchFactorName.LOCATION,
                self._text_similarity(lost.location, found.location),
            ),
            self._factor(MatchFactorName.DATE, self._date_similarity(lost, found)),
        ]
        identity, identity_weight = self._group_result(
            factors, MatchFactorGroup.IDENTITY
        )
        context, context_weight = self._group_result(factors, MatchFactorGroup.CONTEXT)
        compatible = type_similarity is None or type_similarity >= 0.35
        percentage = round(
            identity * self._identity_share + context * self._context_share
        )
        if not compatible:
            percentage = min(percentage, 29)
        if compatible and percentage >= 85:
            level = MatchLevel.HIGH
        elif compatible and percentage >= 60:
            level = MatchLevel.POSSIBLE
        else:
            level = MatchLevel.LOW

        warnings = []
        if not compatible:
            warnings.append("Tipos de objeto incompatibles: similitud inferior al 35%.")
        lost_secondary = self._colors(lost.secondary_colors)
        found_secondary = self._colors(found.secondary_colors)
        if lost_secondary and found_secondary and not lost_secondary & found_secondary:
            warnings.append("Los colores secundarios son incompatibles.")
        conflicts = [
            factor.label
            for factor in factors
            if factor.name in {MatchFactorName.CATEGORY, MatchFactorName.BRAND}
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
        if (
            lost.event_date is not None
            and found.event_date is not None
            and found.event_date < lost.event_date
        ):
            warnings.append("La fecha del hallazgo es anterior a la pérdida.")
        return MatchEvaluation(
            percentage=percentage,
            identity_percentage=round(identity, 2),
            context_percentage=round(context, 2),
            evidence_coverage=round(
                identity_weight * self._identity_share
                + context_weight * self._context_share,
                2,
            ),
            compatible=compatible,
            level=level,
            factors=factors,
            warnings=warnings,
        )

    @staticmethod
    def _group_result(
        factors: list[MatchFactor], group: MatchFactorGroup
    ) -> tuple[float, float]:
        evaluated = [
            factor
            for factor in factors
            if factor.group == group and factor.status != MatchFactorStatus.UNKNOWN
        ]
        weight = sum(factor.evaluable_weight for factor in evaluated)
        points = sum(factor.score for factor in evaluated)
        return (points / weight * 100 if weight else 0.0), weight

    def _factor(
        self,
        name: MatchFactorName,
        similarity: float | None,
        evaluable_weight: float | None = None,
    ) -> MatchFactor:
        identity = name in self._identity_weights
        weight = (self._identity_weights if identity else self._context_weights)[name]
        if similarity is None:
            status = MatchFactorStatus.UNKNOWN
            evaluable_weight = 0.0
            explanation = "Sin datos comparables; se excluye del máximo evaluable."
        else:
            if evaluable_weight is None:
                evaluable_weight = float(weight)
            if similarity == 1:
                status = MatchFactorStatus.MATCH
                explanation = "Los datos coinciden tras normalizar el texto."
            elif similarity == 0:
                status = MatchFactorStatus.DIFFERENT
                explanation = "No hay coincidencia en los datos comparados."
            else:
                status = MatchFactorStatus.PARTIAL
                explanation = (
                    f"Coincidencia parcial del {similarity:.0%} en este factor."
                )
            if evaluable_weight < weight:
                explanation += (
                    f" Se pudieron evaluar {evaluable_weight:g} de {weight} puntos."
                )
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
            group=MatchFactorGroup.IDENTITY if identity else MatchFactorGroup.CONTEXT,
            label=self._labels[name],
            weight=weight,
            evaluable_weight=evaluable_weight,
            score=round(evaluable_weight * (similarity or 0), 2),
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
    def _description_tokens(cls, value: str | None, locations: set[str]) -> set[str]:
        return cls._tokens(value) - locations - cls._report_words

    @classmethod
    def _feature_similarity(
        cls, lost: MatchableObject, found: MatchableObject
    ) -> float | None:
        # Preserve feature boundaries instead of mixing all words into one bag.
        left = {
            frozenset(tokens)
            for value in [*lost.visible_features, *lost.visible_text]
            if (tokens := cls._tokens(value))
        }
        right = {
            frozenset(tokens)
            for value in [*found.visible_features, *found.visible_text]
            if (tokens := cls._tokens(value))
        }
        if not left or not right:
            return None
        forward = sum(max(len(a & b) / len(a | b) for b in right) for a in left) / len(
            left
        )
        backward = sum(max(len(a & b) / len(a | b) for a in left) for b in right) / len(
            right
        )
        return (forward + backward) / 2

    @classmethod
    def _colors(cls, values: list[str]) -> set[str]:
        return {
            " ".join(sorted(tokens))
            for value in values
            if (tokens := cls._tokens(value))
        }

    @classmethod
    def _color_similarity(
        cls, lost: MatchableObject, found: MatchableObject
    ) -> tuple[float | None, float]:
        primary = cls._exact_similarity(
            " ".join(sorted(cls._tokens(lost.primary_color))),
            " ".join(sorted(cls._tokens(found.primary_color))),
        )
        secondary = cls._set_similarity(
            cls._colors(lost.secondary_colors), cls._colors(found.secondary_colors)
        )
        weight = cls._identity_weights[MatchFactorName.COLOR]
        points = 0.0
        evaluable = 0.0
        for similarity, share in ((primary, 0.6), (secondary, 0.4)):
            if similarity is not None:
                evaluable += weight * share
                points += weight * share * similarity
        return (points / evaluable if evaluable else None), evaluable

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
