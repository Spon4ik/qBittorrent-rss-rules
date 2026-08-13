from __future__ import annotations

from pathlib import Path


def create_stremio_local_storage(
    root: Path,
    *,
    auth_key: str = "auth-key",
    user_id: str = "0123456789abcdef",
) -> Path:
    storage_path = (
        root
        / "stremio-shell-ng.exe.WebView2"
        / "EBWebView"
        / "Default"
        / "Local Storage"
        / "leveldb"
    )
    storage_path.mkdir(parents=True, exist_ok=True)
    payload = (
        '\x00noise{"auth":{"key":"' + auth_key + '","user":{"_id":"' + user_id + '"}}}\x00tail'
    )
    (storage_path / "000001.ldb").write_bytes(payload.encode("utf-8"))
    return storage_path


def create_chromium_stremio_local_storage(
    root: Path,
    *,
    auth_key: str = "0123456789abcdef0123456789abcdef0123456789a=",
    user_id: str = "0123456789abcdef",
) -> Path:
    storage_path = (
        root
        / "stremio-shell-ng.exe.WebView2"
        / "EBWebView"
        / "Default"
        / "Local Storage"
        / "leveldb"
    )
    storage_path.mkdir(parents=True, exist_ok=True)
    payload = (
        '\x00record{"auth":\x03\x00 key\x00\x00i"'
        + auth_key
        + '","user":\x00{"_id":"'
        + user_id
        + '"}}\x00tail'
    )
    (storage_path / "000002.ldb").write_bytes(payload.encode("utf-8"))
    return storage_path


def stremio_library_item(
    item_id: str,
    title: str,
    *,
    item_type: str = "series",
    removed: bool = False,
    temp: bool = False,
    completed: bool = False,
    state_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    state: dict[str, object] = {
        "lastWatched": "",
        "timeWatched": 0,
        "timeOffset": 0,
        "overallTimeWatched": 0,
        "timesWatched": 0,
        "flaggedWatched": 0,
        "duration": 0,
        "video_id": "",
        "watched": "",
        "noNotif": False,
        "season": 0,
        "episode": 0,
    }
    if item_type == "movie" and completed:
        state.update(
            {
                "lastWatched": "2026-03-27T17:38:42.732Z",
                "timeWatched": 5_796_000,
                "overallTimeWatched": 5_796_000,
                "timesWatched": 1,
                "flaggedWatched": 1,
                "duration": 5_776_542,
                "video_id": item_id,
                "watched": "undefined:1:eJwDAAAAAAE=",
            }
        )
    if state_overrides:
        state.update(state_overrides)
    return {
        "_id": item_id,
        "name": title,
        "type": item_type,
        "removed": removed,
        "temp": temp,
        "state": state,
    }
