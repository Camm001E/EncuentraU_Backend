from datetime import date

import pytest

from app.application.matching_service import MatchingService
from app.domain.evidence_comparison import (
    compare_features,
    compare_visual,
    object_type_similarity,
)
from app.domain.matching import (
    MatchableObject,
    MatchFactorName,
    MatchFactorStatus,
    MatchRequest,
)
from app.domain.semantic_normalization import (
    description_features,
    features,
    geometry,
    tokens,
)


@pytest.mark.parametrize(
    "left,right",
    [
        ("audífonos de diadema", "audífonos"),
        ("calculadoras científicas", "calculadora"),
        ("botella térmica", "botella"),
        ("MOCHILAS", "morral"),
        ("botella térmica", "termo"),
    ],
)
def test_type_inclusion_is_symmetric(left, right):
    assert (
        object_type_similarity(left, right) == object_type_similarity(right, left) == 1
    )


def test_unrelated_types_remain_zero():
    assert object_type_similarity("audífonos", "calculadora") == 0


@pytest.mark.parametrize(
    "left,right",
    [
        ("botella térmica", "mochila térmica"),
        ("audífonos Bluetooth", "teclado inalámbrico"),
        ("botella de plástico negra", "mochila de plástico negra"),
        ("reloj rectangular", "calculadora rectangular"),
    ],
)
def test_shared_adjectives_do_not_make_unrelated_types_compatible(left, right):
    assert object_type_similarity(left, right) == 0


@pytest.mark.parametrize(
    "left,right",
    [
        ("redonda", "circular"),
        ("elípticas", "ovalada"),
        ("cuadrada", "rectangular"),
        ("arqueada", "curva"),
        ("cilíndrica alargada", "cilíndrico"),
    ],
)
def test_geometry_normalizes_only_geometrical_evidence(left, right):
    assert geometry(left) & geometry(right)


@pytest.mark.parametrize(
    "value", ["diadema", "mochila", "electrónica", "botón", "no visible", None]
)
def test_a_component_or_category_is_not_geometry(value):
    assert not geometry(value)


@pytest.mark.parametrize(
    "left,right",
    [
        ("cierre roto", "cremallera dañada"),
        ("costura roja doble en la banda", "dos líneas rojas cosidas en la diadema"),
        ("raspón diagonal en la esquina", "marca oblicua en el borde"),
        ("llavero circular", "llavero redondo"),
    ],
)
def test_general_feature_paraphrases(left, right):
    result = compare_features(features([left]), features([right]))
    assert result.similarity is not None and result.similarity >= 0.75
    assert result == compare_features(features([right]), features([left]))


@pytest.mark.parametrize(
    "left,right",
    [
        ("parche azul cosido", "costura roja"),
        ("dos botones", "tres botones"),
        ("cierre roto", "nuevo sin daños"),
        ("llavero triangular", "llavero circular"),
    ],
)
def test_distinctive_conflicts_do_not_match(left, right):
    assert compare_features(features([left]), features([right])).similarity == 0


def test_feature_boundaries_prevent_swapping_attributes():
    result = compare_features(
        features(["banda verde", "pieza metálica"]),
        features(["banda metálica", "pieza verde"]),
    )
    assert result.similarity is not None and result.similarity < 1


def test_duplicates_synonyms_and_order_do_not_inflate_results():
    left = features(["cierre roto", "parche amarillo cosido"])
    right = features(["cremallera dañada", "parche verde cosido"])
    original = compare_features(left, right)
    assert (
        compare_features(
            features(
                ["cierre roto", "cremallera dañada", "parche amarillo cosido"] * 3
            ),
            right,
        )
        == original
    )
    assert compare_features(right, left) == original


def test_generic_type_colour_and_material_do_not_form_a_visual_identity():
    assert not features(
        ["objeto negro de plástico", "audífonos negros de plástico"],
        tokens("audífonos"),
    )
    assert not features(["pieza de plástico negra", "parte negra de plástico"])


def test_description_ignores_type_category_context_and_dates():
    ignored = tokens("mochila bolsos biblioteca central")
    assert (
        description_features(
            "Perdí una mochila en biblioteca central el 2026-10-18", ignored
        )
        == frozenset()
    )
    assert description_features(
        "mochila con cremallera dañada", ignored
    ) == description_features(
        "Encontré un morral con cierre roto en biblioteca central", ignored
    )


def test_missing_text_is_unknown_but_different_known_text_is_a_conflict():
    visual = features(["cierre roto"])
    assert compare_visual(visual, visual, ["AB-12"], []).similarity == 1
    conflict = compare_visual(visual, visual, ["AB-12"], ["AB+12"])
    assert conflict.similarity < 1
    assert conflict.contradictions


@pytest.mark.parametrize("unknown", ["No visible", "N/A", "desconocido"])
def test_unknown_visible_text_does_not_become_a_known_contradiction(unknown):
    visual = features(["cierre roto"])
    result = compare_visual(visual, visual, [unknown], ["ZX-23"])
    assert result.similarity == 1
    assert not result.contradictions


def test_shape_unknown_is_excluded_but_known_contradiction_is_evaluable():
    obj = MatchableObject(object_type="recipiente", shape="cilíndrico")
    service = MatchingService()

    def shape(value):
        result = service.evaluate(
            MatchRequest(lost=obj, found=obj.model_copy(update={"shape": value}))
        )
        return next(f for f in result.factors if f.name == MatchFactorName.SHAPE)

    assert shape("tapa").status == MatchFactorStatus.UNKNOWN
    assert shape("tapa").evaluable_weight == 0
    assert shape("rectangular").status == MatchFactorStatus.DIFFERENT
    assert shape("rectangular").evaluable_weight == 10


def test_same_type_is_not_physical_identity_when_distinctive_evidence_conflicts():
    common = dict(
        object_type="mochila",
        category="bolsos",
        primary_color="negro",
        location="Biblioteca",
        event_date=date(2026, 10, 18),
    )
    lost = MatchableObject(
        **common,
        visible_features=["cierre roto", "parche triangular"],
        description="mochila con cierre roto y parche triangular",
    )
    same = MatchableObject(
        **common,
        visible_features=["cremallera dañada", "parche triangular"],
        description="morral con cremallera dañada y parche triangular",
    )
    different = MatchableObject(
        **common,
        visible_features=["nuevo sin daños", "parche circular"],
        description="mochila nueva sin daños con parche circular",
    )
    service = MatchingService()
    yes = service.evaluate(MatchRequest(lost=lost, found=same))
    no = service.evaluate(MatchRequest(lost=lost, found=different))
    assert yes.percentage > no.percentage
    assert no.percentage < 85
    assert no.compatible


def test_no_division_by_zero_for_absent_semantic_evidence():
    assert compare_features(frozenset(), frozenset()).similarity is None
    result = MatchingService().evaluate(
        MatchRequest(lost=MatchableObject(), found=MatchableObject())
    )
    assert result.percentage == result.evidence_coverage == 0


def test_generic_piece_requires_comparable_region_and_attributes():
    known = features(["remache dorado en la bisagra"])
    located = features(["pieza circular dorada cerca de la unión"])
    unsupported = features(["pieza circular dorada"])
    elsewhere = features(["pieza circular dorada en la base"])
    assert compare_features(known, located).similarity >= 0.75
    assert compare_features(known, unsupported).similarity == 0
    assert compare_features(known, elsewhere).similarity == 0


def test_description_does_not_duplicate_type_and_generic_primary_colour():
    assert not description_features(
        "Encontré una mochila negra en biblioteca", tokens("mochila biblioteca")
    )


@pytest.mark.parametrize(
    "value,head,attribute",
    [
        ("bolsillo cosido", "bolsillo", "costura"),
        ("tapa rayada", "tapa", "dano"),
        ("cierre roto", "cierre", "dano"),
    ],
)
def test_adjectival_observations_remain_with_their_component(value, head, attribute):
    parsed = description_features(value, frozenset())
    assert len(parsed) == 1
    observation = next(iter(parsed))
    # Either nucleus can name the observation; the relation must stay intact.
    assert {head, attribute} <= {observation.head, *observation.attributes}


def test_separate_noun_observations_keep_their_boundaries():
    parsed = description_features("parche triangular y costura doble", frozenset())
    assert {observation.head for observation in parsed} == {"parche", "costura"}


@pytest.mark.parametrize("value", ["costura", "cierre", "llavero", "parche cosido"])
def test_identical_distinctive_observation_is_reflexive(value):
    observed = features([value])
    assert observed
    assert compare_features(observed, observed).similarity == 1


def test_scoring_policy_is_unchanged():
    service = MatchingService()
    assert service._identity_share == 0.8 and service._context_share == 0.2
    assert {k.value: v for k, v in service._identity_weights.items()} == {
        "object_type": 25,
        "category": 5,
        "color": 15,
        "brand": 10,
        "shape": 10,
        "visual_features": 20,
        "description": 15,
    }
    assert {k.value: v for k, v in service._context_weights.items()} == {
        "location": 60,
        "date": 40,
    }
    assert (
        service._high_threshold,
        service._possible_threshold,
        service._incompatible_ceiling,
        service._type_compatibility_threshold,
    ) == (85, 60, 29, 0.35)


@pytest.mark.parametrize(
    "types,shape,other_shape,feature,other_feature",
    [
        (
            ("botella térmica", "termo"),
            "cilíndrica",
            "rectangular",
            "tapa metálica con cierre",
            "tapa plástica sin cierre",
        ),
        (
            ("llaves", "llaves"),
            "alargada",
            "alargada",
            "llavero circular",
            "llavero triangular",
        ),
    ],
)
def test_general_objects_rank_equivalent_evidence_above_conflicting_evidence(
    types, shape, other_shape, feature, other_feature
):
    common = dict(
        category="accesorios",
        primary_color="verde",
        location="Portería",
        event_date=date(2026, 10, 18),
    )
    left = MatchableObject(
        **common,
        object_type=types[0],
        shape=shape,
        visible_features=[feature],
        description=feature,
    )
    equivalent = MatchableObject(
        **common,
        object_type=types[1],
        shape=shape,
        visible_features=[feature],
        description=feature,
    )
    conflicting = equivalent.model_copy(
        update={
            "shape": other_shape,
            "visible_features": [other_feature],
            "description": other_feature,
        }
    )
    service = MatchingService()
    same = service.evaluate(MatchRequest(lost=left, found=equivalent))
    other = service.evaluate(MatchRequest(lost=left, found=conflicting))
    assert same.percentage >= 85
    assert other.percentage < 85
    assert same.percentage >= other.percentage + 5


@pytest.mark.parametrize(
    "identity,context,percentage,level",
    [
        (100, 0, 80, "possible"),
        (0, 100, 20, "low"),
        (85, 85, 85, "high"),
        (84, 84, 84, "possible"),
        (60, 60, 60, "possible"),
        (59, 59, 59, "low"),
    ],
)
def test_policy_thresholds_and_group_shares_are_applied(
    monkeypatch, identity, context, percentage, level
):
    service = MatchingService()
    monkeypatch.setattr(
        service,
        "_group_result",
        lambda _, group: (identity if group.value == "identity" else context, 100),
    )
    obj = MatchableObject(object_type="mochila")
    result = service.evaluate(MatchRequest(lost=obj, found=obj))
    assert result.percentage == percentage
    assert result.level.value == level
