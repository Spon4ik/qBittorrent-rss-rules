"""Audit the maintained deterministic regression inventory."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]

# Add an entry whenever a reported issue is confirmed.  A repair is not
# considered complete until its exact regression test is present.
KNOWN_ISSUES = (
    ("docker_wrapper_requires_runtime_freshness_before_success", "tests/test_runtime_status.py"),
    (
        "terminal_acceleration_failure_records_one_deterministic_incident",
        "tests/test_download_acceleration.py",
    ),
    ("service_persists_provider_id_before_resuming_without_duplicate_submission", "tests/test_download_acceleration.py"),
    ("login_accepts_no_content_response_with_session_cookie", "tests/test_qbittorrent_client.py"),
    ("add_torrent_url_accepts_duplicate_conflict", "tests/test_qbittorrent_client.py"),
    ("add_torrent_file_accepts_duplicate_conflict", "tests/test_qbittorrent_client.py"),
    (
        "set_file_priority_does_not_treat_missing_torrent_as_missing_endpoint",
        "tests/test_qbittorrent_client.py",
    ),
    (
        "queue_result_with_optional_file_selection_applies_qb_file_priorities",
        "tests/test_selective_queue.py",
    ),
    ("jackett_client_scoped_search_keeps_working_tracker_after_mixed_failures", "tests/test_jackett.py"),
    ("saved_indexer_scope_never_searches_aggregate_all_endpoint", "tests/test_jackett.py"),
    ("stremio_write_unwatched_movie_clears_stale_completion_markers", "tests/test_stremio.py"),
    ("watch_progress_sync_skips_stremio_episode_missing_from_jellyfin", "tests/test_watch_progress_sync.py"),
    ("edit_rule_saved_snapshot_hides_broad_imdb_title_fallback_rows", "tests/test_routes.py"),
    ("inline_local_filters_enforce_query_and_imdb_parity", "tests/test_routes.py"),
    ("queue_result_with_optional_file_selection_does_not_remote_fetch_broken_local_jackett_url", "tests/test_selective_queue.py"),
    ("jellyfin_auto_sync_retries_transient_sqlite_locks_without_error_status", "tests/test_jellyfin_auto_sync.py"),
    ("rules_fetch_batch_retries_failed_rule_once_and_clears_partial_status", "tests/test_rule_fetch_ops.py"),
)


def audit() -> list[str]:
    missing: list[str] = []
    for test_name, relative_path in KNOWN_ISSUES:
        source = (PROJECT_DIR / relative_path).read_text(encoding="utf-8")
        if not re.search(rf"^def test_{re.escape(test_name)}\(", source, re.MULTILINE):
            missing.append(f"{relative_path}::{test_name}")
    return missing


if __name__ == "__main__":
    missing = audit()
    if missing:
        print("Missing deterministic issue regressions:")
        print("\n".join(missing))
        raise SystemExit(1)
    print(f"Issue regression audit passed: {len(KNOWN_ISSUES)} entries")
