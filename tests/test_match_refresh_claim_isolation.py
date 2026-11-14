from datetime import date

import pytest


def test_claim_on_another_pair_does_not_freeze_pending_match_scores(workflow):
    w = workflow
    if w.engine.dialect.name != "postgresql":
        pytest.skip("Match generation uses PostgreSQL advisory locks and upserts.")
    assert w.claim().status_code == 201
    protected = w.client.get(
        f"/api/v1/matches/{w.match_id}", headers=w.headers["A"]
    ).json()
    ids = {}
    for actor, kind, title in (
        ("A", "lost", "sombrilla"),
        ("B", "found", "paraguas plegable"),
    ):
        response = w.client.post(
            "/api/v1/reports",
            headers=w.headers[actor],
            json={
                "report_type": kind,
                "object_type": title,
                "category": "accesorio",
                "primary_color": "negro",
                "shape": "alargada",
                "description": "Tela negra y mango redondo con cordón.",
                "location": "Recepción",
                "event_date": date.today().isoformat(),
            },
        )
        assert response.status_code == 201, response.json()
        ids[actor] = response.json()["id"]

    def generated():
        response = w.client.post(
            f"/api/v1/reports/{ids['A']}/matches/generate", headers=w.headers["A"]
        )
        assert response.status_code == 200, response.json()
        return next(
            row
            for row in response.json()["items"]
            if row["candidate_report"]["id"] == ids["B"]
        )

    before = generated()
    response = w.client.patch(
        f"/api/v1/reports/{ids['B']}",
        headers=w.headers["B"],
        json={"primary_color": "blanco"},
    )
    assert response.status_code == 200
    after = generated()
    color = next(f for f in after["factors"] if f["name"] == "color")
    assert color["score"] == 0
    assert after["percentage"] < before["percentage"]
    assert after["id"] == before["id"]
    assert (
        w.client.post(
            f"/api/v1/reports/{w.lost_id}/matches/generate", headers=w.headers["A"]
        ).status_code
        == 200
    )
    assert (
        w.client.get(f"/api/v1/matches/{w.match_id}", headers=w.headers["A"]).json()
        == protected
    )
