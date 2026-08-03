from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from myjdapi import Myjdapi  # type: ignore[import-untyped]


class MyJDownloaderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MyJDownloaderDevice:
    id: str
    name: str
    type: str


class MyJDownloaderClient:
    def __init__(self, *, api_factory: Callable[[], Any] = Myjdapi) -> None:
        self._api_factory = api_factory

    def list_devices(self, *, email: str, password: str) -> list[MyJDownloaderDevice]:
        api = self._connect(email=email, password=password)
        try:
            devices = api.list_devices() or []
            return [
                MyJDownloaderDevice(
                    id=str(item.get("id") or "").strip(),
                    name=str(item.get("name") or "").strip(),
                    type=str(item.get("type") or "").strip(),
                )
                for item in devices
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ]
        finally:
            self._disconnect(api)

    def add_links(
        self,
        *,
        email: str,
        password: str,
        device_id: str,
        links: list[str],
        package_name: str,
        destination_folder: str,
        autostart: bool = True,
    ) -> str:
        cleaned_links = [str(link).strip() for link in links if str(link).strip()]
        if not cleaned_links:
            raise MyJDownloaderError("No download links were provided to MyJDownloader.")
        api = self._connect(email=email, password=password)
        try:
            device = api.get_device(device_id=device_id)
            response = device.linkgrabber.add_links(
                [
                    {
                        "autostart": bool(autostart),
                        "links": "\n".join(cleaned_links),
                        "packageName": str(package_name or "Real-Debrid download").strip(),
                        "extractPassword": None,
                        "priority": "DEFAULT",
                        "downloadPassword": None,
                        "destinationFolder": str(destination_folder or "").strip() or None,
                        "overwritePackagizerRules": True,
                    }
                ]
            )
            job_id = str(response or "").strip()
            if not job_id:
                raise MyJDownloaderError("MyJDownloader did not return a LinkGrabber job ID.")
            return job_id
        except MyJDownloaderError:
            raise
        except Exception as exc:
            raise MyJDownloaderError(
                f"MyJDownloader link submission failed ({exc.__class__.__name__})."
            ) from exc
        finally:
            self._disconnect(api)

    def _connect(self, *, email: str, password: str) -> Any:
        if not (str(email or "").strip() and password):
            raise MyJDownloaderError("MyJDownloader credentials are incomplete.")
        api = self._api_factory()
        try:
            api.connect(str(email).strip(), password)
        except Exception as exc:
            raise MyJDownloaderError(
                f"MyJDownloader connection failed ({exc.__class__.__name__})."
            ) from exc
        return api

    @staticmethod
    def _disconnect(api: Any) -> None:
        try:
            api.disconnect()
        except Exception:
            pass
