from __future__ import annotations

from app.config import obfuscate_secret
from app.models import AppSettings, DownloadAccelerationJob


def _settings(*, myjd: bool = False) -> AppSettings:
    return AppSettings(
        id="default",
        qb_base_url="http://qb.test",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("qb-secret"),
        real_debrid_enabled=True,
        real_debrid_client_id_encrypted=obfuscate_secret("client"),
        real_debrid_client_secret_encrypted=obfuscate_secret("client-secret"),
        real_debrid_access_token_encrypted=obfuscate_secret("access"),
        real_debrid_refresh_token_encrypted=obfuscate_secret("refresh"),
        myjd_enabled=myjd,
        myjd_email="user@example.test" if myjd else None,
        myjd_password_encrypted=obfuscate_secret("jd-secret") if myjd else None,
        myjd_device_id="device-1" if myjd else None,
    )


def test_real_debrid_torrent_queue_resolves_provider_id_to_hash_only_magnet(
    app_client, db_session, monkeypatch
) -> None:
    db_session.add(_settings())
    db_session.commit()
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "app.routes.api.RealDebridClient.get_torrent",
        lambda self, torrent_id: {"id": torrent_id, "hash": "a" * 40},
    )

    def fake_add(self, *, link, **kwargs):
        captured["link"] = link

    monkeypatch.setattr("app.services.selective_queue.QbittorrentClient.add_torrent_url", fake_add)
    response = app_client.post(
        "/api/search/queue",
        json={
            "link": "real-debrid://torrent/rd-1",
            "source_kind": "real_debrid_torrent",
            "provider_id": "rd-1",
            "info_hash": "a" * 40,
        },
    )
    assert response.status_code == 200
    assert captured["link"] == f"magnet:?xt=urn:btih:{'a' * 40}"


def test_real_debrid_history_queue_is_myjdownloader_only_and_idempotent(
    app_client, db_session, monkeypatch
) -> None:
    db_session.add(_settings(myjd=True))
    db_session.commit()
    submitted: list[list[str]] = []

    monkeypatch.setattr(
        "app.routes.api.RealDebridClient.list_downloads",
        lambda self, page, limit: [
            {"id": "download-1", "filename": "history.mkv", "link": "restricted"}
        ],
    )
    monkeypatch.setattr(
        "app.routes.api.RealDebridClient.unrestrict_link",
        lambda self, link: {"download": "https://cdn.test/history.mkv"},
    )

    def fake_add(self, **kwargs):
        submitted.append(kwargs["links"])
        return "jd-job-1"

    monkeypatch.setattr("app.routes.api.MyJDownloaderClient.add_links", fake_add)
    request = {
        "link": "real-debrid://download/download-1",
        "source_kind": "real_debrid_download",
        "provider_id": "download-1",
        "queue_capability": "jdownloader",
    }
    first = app_client.post("/api/search/queue", json=request)
    second = app_client.post("/api/search/queue", json=request)
    assert first.status_code == 200
    assert first.json()["message"] == "Queued in MyJDownloader."
    assert second.json()["status"] == "already_queued"
    assert submitted == [["https://cdn.test/history.mkv"]]
    job = db_session.query(DownloadAccelerationJob).one()
    assert job.provider_download_id == "download-1"
    assert job.myjd_job_ids == ["jd-job-1"]
