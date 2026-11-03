from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import export as svc

STATE = {
    "providers": {
        "TRAKT": {
            "history": {"baseline": {"items": {
                "movie:tmdb:949": {"type": "movie", "title": "Heat", "year": 1995,
                                   "ids": {"imdb": "tt0113277", "tmdb": "949"}, "watched_at": "2026-01-02T20:00:00Z"},
                "episode:tmdb:999": {"type": "episode", "title": "Pilot", "series_title": "MobLand", "season": 1, "episode": 1,
                                     "ids": {"tmdb": "999"}, "show_ids": {"imdb": "tt31510819", "tmdb": "247718"},
                                     "watched_at": "2026-02-03T21:00:00Z"},
            }}},
            "ratings": {"baseline": {"items": {
                "movie:tmdb:949": {"type": "movie", "title": "Heat", "year": 1995, "ids": {"imdb": "tt0113277"},
                                   "rating": 9, "rated_at": "2026-01-03T10:00:00Z"},
            }}},
        },
    },
}


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(svc, "_load_state", lambda features=None: STATE)
    monkeypatch.setattr(svc, "_load_config_safe", lambda: {})
    monkeypatch.setattr(svc, "_provider_rewatch_read_supported", lambda provider: False)
    app = FastAPI()
    app.include_router(svc.router)
    return TestClient(app)


def test_history_items_carry_ids_dates_and_episode_show_ids(monkeypatch) -> None:
    body = _client(monkeypatch).get("/api/export/items", params={"provider": "trakt", "feature": "history"}).json()
    assert body["total"] == 2
    assert body["items"] == [
        {"key": "episode:tmdb:999", "type": "episode", "title": "Pilot", "year": "", "ids": {"tmdb": "999"},
         "series_title": "MobLand", "show_ids": {"imdb": "tt31510819", "tmdb": "247718"}, "season": 1, "episode": 1,
         "watched_at": "2026-02-03T21:00:00Z"},
        {"key": "movie:tmdb:949", "type": "movie", "title": "Heat", "year": "1995",
         "ids": {"imdb": "tt0113277", "tmdb": "949"}, "watched_at": "2026-01-02T20:00:00Z"},
    ]


def test_ratings_items_carry_rating_and_paging_slices(monkeypatch) -> None:
    client = _client(monkeypatch)
    body = client.get("/api/export/items", params={"provider": "TRAKT", "feature": "ratings"}).json()
    assert body["items"] == [{"key": "movie:tmdb:949", "type": "movie", "title": "Heat", "year": "1995",
                              "ids": {"imdb": "tt0113277"}, "rating": 9, "rated_at": "2026-01-03T10:00:00Z"}]
    page = client.get("/api/export/items", params={"provider": "TRAKT", "offset": 1, "limit": 1}).json()
    assert [row["key"] for row in page["items"]] == ["movie:tmdb:949"]
    assert page["total"] == 2


def test_rejects_unsupported_feature_and_missing_provider(monkeypatch) -> None:
    client = _client(monkeypatch)
    assert client.get("/api/export/items", params={"provider": "TRAKT", "feature": "watchlist"}).status_code == 422
    assert client.get("/api/export/items").status_code == 422
    assert client.get("/api/export/items", params={"provider": "PLEX"}).json()["items"] == []


def test_crosswatch_tracker_reads_its_own_store_and_collapses_rewatches(monkeypatch) -> None:
    client = _client(monkeypatch)
    tracker = {
        "tmdb:100": {"type": "movie", "title": "Lock, Stock", "ids": {"imdb": "tt0120735"},
                     "watched_at": "2016-08-23T08:39:00.000Z"},
        "imdb:tt0369277#s01e01": {"type": "episode", "title": "S01E01", "series_title": "Bible Black",
                                  "season": 1, "episode": 1, "ids": {"tvdb": "4344192"},
                                  "show_ids": {"imdb": "tt0369277"}, "watched_at": "2014-02-19T15:33:00.000Z"},
    }
    calls: list[tuple[str, object]] = []

    def load_state(kind, snapshot=None, provider_instance=None):
        calls.append((kind, provider_instance))
        return {"items": tracker if kind == "history" else {}, "ts": 0}

    monkeypatch.setattr(svc.editor, "load_state", load_state)
    body = client.get("/api/export/items", params={"provider": "CROSSWATCH"}).json()
    assert body["total"] == 2
    assert [row["key"] for row in body["items"]] == ["imdb:tt0369277#s01e01", "tmdb:100"]
    assert body["items"][0]["show_ids"] == {"imdb": "tt0369277"}
    assert client.get("/api/export/items", params={"provider": "CROSSWATCH", "feature": "ratings"}).json()["items"] == []
    assert calls == [("history", "all"), ("ratings", "all")]
