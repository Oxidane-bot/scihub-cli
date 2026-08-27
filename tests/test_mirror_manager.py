from scihub_cli.core.mirror_manager import MirrorManager


class _MirrorResponse:
    def __init__(self, *, status_code=200, text="", content=None):
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode()


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


def test_mirror_health_check_does_not_accept_home_page_200(monkeypatch):
    mirror = "https://mirror.example"
    manager = MirrorManager(mirrors=[mirror], timeout=1)
    calls = []

    def fake_get(url, **kwargs):  # noqa: ARG001
        calls.append(url)
        return _MirrorResponse(text="<html><title>Sci-Hub</title><body>Welcome</body></html>")

    monkeypatch.setattr("scihub_cli.core.mirror_manager.requests.get", fake_get)

    assert manager._test_mirror(mirror) is False
    assert calls == ["https://mirror.example/10.1038@323533a0"]


def test_mirror_health_check_requires_article_pdf_link(monkeypatch):
    mirror = "https://mirror.example"
    manager = MirrorManager(mirrors=[mirror], timeout=1)
    calls = []
    html = (
        '<html><body><iframe id="pdf" src="/downloads/10.1038/323533a0.pdf"></iframe></body></html>'
    )

    def fake_get(url, **kwargs):  # noqa: ARG001
        calls.append(url)
        return _MirrorResponse(text=html)

    monkeypatch.setattr("scihub_cli.core.mirror_manager.requests.get", fake_get)

    assert manager._test_mirror(mirror) is True
    assert calls == ["https://mirror.example/10.1038@323533a0"]


def test_mirror_health_check_rejects_block_page(monkeypatch):
    mirror = "https://mirror.example"
    manager = MirrorManager(mirrors=[mirror], timeout=1)
    response = _MirrorResponse(
        text="<html>Scientific Mutual Aid Community. You can request this article.</html>"
    )
    monkeypatch.setattr("scihub_cli.core.mirror_manager.requests.get", lambda *a, **k: response)

    assert manager._test_mirror(mirror) is False
