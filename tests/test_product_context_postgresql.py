from app.domain.matching_version import CURRENT_SCORING_VERSION
from tests.test_matches_postgresql import create_report, generated
from tests.test_reports_postgresql import reports as reports
from tests.test_reports_postgresql import reports_engine as reports_engine


def test_packaging_candidate_retrieved_from_both_accounts_without_editing_reports(
    reports,
):
    common = dict(
        category="jabon",
        primary_color="blanco",
        brand="Cetaphil",
        secondary_colors=["azul"],
        shape="rectangular",
        with_analysis=False,
    )
    lost = create_report(
        reports,
        "lost",
        object_type="jabón facil",
        description="limpiador facial cetaphil",
        **common,
    )
    found = create_report(
        reports,
        "found",
        mine=False,
        object_type="botella dispensadora de limpiador facial",
        description="Jabol facial Cetaphil",
        **common,
    )
    before = [lost, found]
    for report, mine in ((lost, True), (found, False)):
        result = generated(reports, report["id"], mine=mine)
        assert result["total"] == 1
        match = result["items"][0]
        assert (
            match["level"] == "possible"
            and match["scoring_version"] == CURRENT_SCORING_VERSION
        )
        assert match["factors"][0]["score"] == 0
    for report, headers in zip(
        before, (reports.headers, reports.other_headers), strict=True
    ):
        after = reports.client.get(
            "/api/v1/reports/" + report["id"], headers=headers
        ).json()
        assert after == report


def test_other_product_in_similar_container_is_not_retrieved(reports):
    common = dict(
        category="aseo",
        primary_color="blanco",
        brand="Marca de prueba",
        secondary_colors=["azul"],
        shape="rectangular",
        with_analysis=False,
    )
    lost = create_report(
        reports,
        "lost",
        object_type="botella de jabón",
        description="limpiador facial",
        **common,
    )
    create_report(
        reports,
        "found",
        mine=False,
        object_type="botella de crema",
        description="crema facial",
        **common,
    )
    assert generated(reports, lost["id"])["items"] == []


def test_umbrella_alias_retrieved_from_both_accounts_without_visual_analysis(reports):
    common = dict(
        category="accesorio",
        primary_color="negro",
        brand=None,
        secondary_colors=[],
        shape="alargada",
        with_analysis=False,
    )
    lost = create_report(
        reports,
        "lost",
        object_type="sombrilla",
        description="Se me quedó una sombrilla negra con cordón en el mango.",
        **common,
    )
    found = create_report(
        reports,
        "found",
        mine=False,
        object_type="paraguas plegable",
        description=(
            "Hallé un paraguas pequeño cerrado, de tela negra y mango redondo."
        ),
        **common,
    )
    for report, mine in ((lost, True), (found, False)):
        result = generated(reports, report["id"], mine=mine)
        assert result["total"] == 1
        assert result["items"][0]["level"] == "possible"
        assert result["items"][0]["scoring_version"] == CURRENT_SCORING_VERSION
