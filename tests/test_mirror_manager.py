from scihub_cli.core.mirror_manager import MirrorManager


def test_mirror_manager_respects_custom_mirrors(monkeypatch):
    mirrors = ["https://custom-mirror.invalid", "https://backup-mirror.invalid"]
    manager = MirrorManager(mirrors=mirrors, timeout=1)

    def fake_test(mirror: str, allow_403: bool = False) -> bool:  # noqa: ARG001
        return mirror == mirrors[1]

    monkeypatch.setattr(manager, "_test_mirror", fake_test)

    assert manager.get_working_mirror(force_refresh=True) == mirrors[1]
