from scihub_cli.core.mirror_manager import MirrorManager


def test_mirror_manager_respects_custom_mirrors(monkeypatch):
    mirrors = ["https://custom-mirror.invalid", "https://backup-mirror.invalid"]
    manager = MirrorManager(mirrors=mirrors, timeout=1)

    def fake_test(mirror: str, allow_403: bool = False) -> bool:  # noqa: ARG001
        return mirror == mirrors[1]

    monkeypatch.setattr(manager, "_test_mirror", fake_test)

    assert manager.get_working_mirror(force_refresh=True) == mirrors[1]


def test_mirror_manager_retests_when_all_blacklisted(monkeypatch):
    mirrors = ["https://easy-mirror.invalid", "https://hard-mirror.invalid"]
    manager = MirrorManager(mirrors=mirrors, timeout=1)

    manager.mark_failed(mirrors[0])
    manager.mark_failed(mirrors[1])

    def fake_is_hard(mirror: str) -> bool:
        return mirror == mirrors[1]

    def fake_parallel(candidates: list[str], allow_403: bool = False, max_workers: int = 5):  # noqa: ARG001
        # During fallback, easy mirrors are retried first and should recover.
        if candidates == [mirrors[0]]:
            return mirrors[0]
        return None

    monkeypatch.setattr("scihub_cli.core.mirror_manager.MirrorConfig.is_hard_mirror", fake_is_hard)
    monkeypatch.setattr(manager, "_test_mirrors_parallel", fake_parallel)

    chosen = manager.get_working_mirror(force_refresh=True)
    assert chosen == mirrors[0]
