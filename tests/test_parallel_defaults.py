from scihub_cli.config.settings import Settings


def test_default_parallelism_is_four(monkeypatch):
    monkeypatch.delenv("SCIHUB_PARALLEL", raising=False)

    assert Settings.DEFAULT_PARALLEL == 4
    assert Settings().parallel == 4
