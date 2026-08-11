from pathlib import Path

from database import create_team, get_settings, init_db


def main():
    init_db()
    undisputed_id = create_team("UNDISPUTED")
    buckshot_id = create_team("Buckshot")

    from themes import display_theme_state

    state = display_theme_state(get_settings())
    undisputed = state["teams"][str(undisputed_id)]
    buckshot = state["teams"][str(buckshot_id)]

    assert undisputed["base"] == "undisputed"
    assert undisputed["enabled"] is True
    assert undisputed["assets"]["hero"].startswith(
        "/static/theme-packs/undisputed/"
    )
    assert buckshot["base"] == "classic"
    assert buckshot["enabled"] is False

    asset_root = Path("app/static/theme-packs/undisputed")
    for name in (
        "hero.png",
        "bg.jpg",
        "medallion.png",
        "row.jpg",
        "champ.jpg",
        "ctl.png",
        "ctr.png",
        "cbl.png",
        "cbr.png",
        "totmark.png",
    ):
        path = asset_root / name
        assert path.is_file() and path.stat().st_size > 0, name

    import server

    client = server.app.test_client()

    response = client.get("/api/themes")
    assert response.status_code == 200, response.data
    payload = response.get_json()
    assert payload["ok"] is True
    assert any(t["name"] == "UNDISPUTED" for t in payload["teams"])

    response = client.get("/api/leaderboard")
    assert response.status_code == 200, response.data
    leaderboard = response.get_json()
    assert "theme_state" in leaderboard
    assert leaderboard["theme_state"]["teams"][str(undisputed_id)]["base"] == "undisputed"

    response = client.get("/static/theme-packs/undisputed/hero.png")
    assert response.status_code == 200
    assert len(response.data) > 100_000

    print("Theme Studio smoke test passed")


if __name__ == "__main__":
    main()
