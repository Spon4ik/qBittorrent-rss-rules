from __future__ import annotations

from app.services.myjdownloader import MyJDownloaderClient


class FakeLinkgrabber:
    def __init__(self) -> None:
        self.payload = None

    def add_links(self, payload):
        self.payload = payload
        return "job-123"


class FakeDevice:
    def __init__(self) -> None:
        self.linkgrabber = FakeLinkgrabber()


class FakeApi:
    def __init__(self) -> None:
        self.device = FakeDevice()
        self.disconnected = False

    def connect(self, email, password):
        assert (email, password) == ("user@example.test", "secret")

    def list_devices(self):
        return [{"id": "device-1", "name": "Downloader", "type": "jd"}]

    def get_device(self, *, device_id):
        assert device_id == "device-1"
        return self.device

    def disconnect(self):
        self.disconnected = True


def test_lists_devices_and_disconnects() -> None:
    fake = FakeApi()
    client = MyJDownloaderClient(api_factory=lambda: fake)
    devices = client.list_devices(email="user@example.test", password="secret")
    assert [(item.id, item.name) for item in devices] == [("device-1", "Downloader")]
    assert fake.disconnected is True


def test_add_links_sets_destination_autostart_and_packagizer_override() -> None:
    fake = FakeApi()
    client = MyJDownloaderClient(api_factory=lambda: fake)
    job_id = client.add_links(
        email="user@example.test",
        password="secret",
        device_id="device-1",
        links=["https://example.test/a", "https://example.test/b"],
        package_name="Example",
        destination_folder="D:\\Media\\Example",
    )
    assert job_id == "job-123"
    assert fake.device.linkgrabber.payload == [
        {
            "autostart": True,
            "links": "https://example.test/a\nhttps://example.test/b",
            "packageName": "Example",
            "extractPassword": None,
            "priority": "DEFAULT",
            "downloadPassword": None,
            "destinationFolder": "D:\\Media\\Example",
            "overwritePackagizerRules": True,
        }
    ]
    assert fake.disconnected is True
