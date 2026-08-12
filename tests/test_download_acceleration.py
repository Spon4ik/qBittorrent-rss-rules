from __future__ import annotations

from datetime import timedelta

from app.models import AppSettings, DownloadAccelerationJob, utcnow
from app.services.download_acceleration import (
    MAX_JOBS_PER_TICK,
    DownloadAccelerationService,
    match_selected_files,
    metainfo_is_sensitive,
    safe_relative_path,
    tracker_free_magnet,
)
from app.services.real_debrid import RealDebridError

PUBLIC_TORRENT = b"d8:announce21:http://tracker.test/a4:infod6:lengthi4e4:name8:file.mkvee"
PRIVATE_TORRENT = b"d8:announce21:http://tracker.test/a4:infod6:lengthi4e4:name8:file.mkv7:privatei1eee"


class FakeQb:
    def __init__(self) -> None:
        self.added_webseeds: list[str] = []
        self.before_add_webseeds = None

    def get_torrents(self, *, tag=None):
        assert tag == "qb-rss-rules"
        return [{"hash": "a" * 40, "name": "file.mkv", "progress": 0.5, "save_path": "/data"}]

    def get_torrent_files(self, info_hash):
        return [{"index": 0, "name": "file.mkv", "size": 4, "priority": 1}]

    def export_torrent(self, info_hash):
        return PUBLIC_TORRENT

    def get_webseeds(self, info_hash):
        return []

    def add_webseeds(self, info_hash, urls):
        if self.before_add_webseeds is not None:
            self.before_add_webseeds()
        self.added_webseeds.extend(urls)


class FakeRd:
    def __init__(self) -> None:
        self.submissions = 0
        self.selected: list[int] = []

    def add_torrent(self, torrent_bytes, *, filename):
        self.submissions += 1
        return {"id": "rd-1"}

    def add_magnet(self, magnet):
        self.submissions += 1
        return {"id": "rd-1"}

    def get_torrent(self, torrent_id):
        if not self.selected:
            return {
                "status": "waiting_files_selection",
                "files": [{"id": 1, "path": "/file.mkv", "bytes": 4, "selected": 0}],
                "links": [],
            }
        return {
            "status": "downloaded",
            "files": [{"id": 1, "path": "/file.mkv", "bytes": 4, "selected": 1}],
            "links": ["restricted-1"],
        }

    def select_files(self, torrent_id, file_ids):
        self.selected = file_ids


def test_sensitive_metainfo_and_safe_paths() -> None:
    assert metainfo_is_sensitive(PUBLIC_TORRENT) is False
    assert metainfo_is_sensitive(PRIVATE_TORRENT) is True
    assert tracker_free_magnet("A" * 40, "Name") == f"magnet:?xt=urn:btih:{'a' * 40}&dn=Name"
    assert safe_relative_path("folder/file.mkv") == "folder/file.mkv"
    assert safe_relative_path("../secret") is None


def test_file_match_requires_enabled_path_and_size() -> None:
    matched = match_selected_files(
        [{"index": 2, "name": "Show/file.mkv", "size": 10, "priority": 1}],
        [{"id": 8, "path": "/Root/Show/file.mkv", "bytes": 10}],
    )
    assert matched == [
        {
            "qb_id": 2,
            "rd_id": 8,
            "path": "Show/file.mkv",
            "provider_path": "Root/Show/file.mkv",
            "size": 10,
        }
    ]


def test_service_persists_provider_id_before_resuming_without_duplicate_submission(db_session) -> None:
    settings = AppSettings(
        id="default",
        real_debrid_enabled=True,
        real_debrid_webseed_base_url="http://backend.test",
        real_debrid_metadata_wait_seconds=120,
    )
    db_session.add(settings)
    db_session.commit()
    qb = FakeQb()
    rd = FakeRd()
    service = DownloadAccelerationService(
        db_session,
        settings,
        qb_client=qb,
        real_debrid_client=rd,
    )

    service.run_once()
    job = db_session.query(DownloadAccelerationJob).one()
    assert job.provider_torrent_id == "rd-1"
    assert job.state == "provider_downloading"
    assert rd.submissions == 1

    qb.before_add_webseeds = lambda: (
        db_session.expire_all(),
        assert_webseed_mapping_is_committed(db_session),
    )
    service.run_once()
    db_session.refresh(job)
    assert job.state == "webseed_attached"
    assert rd.submissions == 1
    assert qb.added_webseeds == [
        f"http://backend.test/webseeds/real-debrid/{job.webseed_token}/file.mkv"
    ]


def assert_webseed_mapping_is_committed(db_session) -> None:
    persisted = db_session.query(DownloadAccelerationJob).one()
    assert persisted.webseed_token
    assert persisted.webseed_files
    assert persisted.app_webseed_urls


def test_metadata_deadline_is_persisted(db_session) -> None:
    job = DownloadAccelerationJob(
        identity_key="qb:test",
        info_hash="b" * 40,
        metadata_deadline_at=utcnow() - timedelta(seconds=1),
    )
    db_session.add(job)
    db_session.commit()
    assert DownloadAccelerationService._metadata_deadline_passed(job) is True


def test_service_bounds_each_tick_and_prioritizes_newest_active_downloads(db_session) -> None:
    hashes = [f"{index:040x}" for index in range(MAX_JOBS_PER_TICK + 3)]

    class PrioritizedQb(FakeQb):
        def __init__(self) -> None:
            super().__init__()
            self.advanced: list[str] = []

        def get_torrents(self, *, tag=None):
            assert tag == "qb-rss-rules"
            return [
                {
                    "hash": info_hash,
                    "name": f"{info_hash}.mkv",
                    "progress": 0.5,
                    "state": "downloading" if index > 0 else "stoppedDL",
                    "added_on": index,
                    "save_path": "/data",
                }
                for index, info_hash in enumerate(hashes)
            ]

        def get_torrent_files(self, info_hash):
            self.advanced.append(info_hash)
            return []

    settings = AppSettings(id="default", real_debrid_metadata_wait_seconds=120)
    db_session.add(settings)
    db_session.commit()
    qb = PrioritizedQb()

    DownloadAccelerationService(
        db_session,
        settings,
        qb_client=qb,
        real_debrid_client=FakeRd(),
    ).run_once()

    assert qb.advanced == list(reversed(hashes[1:]))[:MAX_JOBS_PER_TICK]


def test_invalid_exported_metainfo_falls_back_to_tracker_free_magnet(db_session) -> None:
    class InvalidMetainfoRd(FakeRd):
        def __init__(self) -> None:
            super().__init__()
            self.magnets: list[str] = []

        def add_torrent(self, torrent_bytes, *, filename):
            raise RealDebridError("Real-Debrid torrent_file_invalid (30).")

        def add_magnet(self, magnet):
            self.magnets.append(magnet)
            return {"id": "rd-magnet"}

    settings = AppSettings(id="default", real_debrid_metadata_wait_seconds=120)
    db_session.add(settings)
    db_session.commit()
    rd = InvalidMetainfoRd()

    DownloadAccelerationService(
        db_session,
        settings,
        qb_client=FakeQb(),
        real_debrid_client=rd,
    ).run_once()

    job = db_session.query(DownloadAccelerationJob).one()
    assert job.provider_torrent_id == "rd-magnet"
    assert rd.magnets == [tracker_free_magnet("a" * 40, "file.mkv")]
