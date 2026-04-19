"""Shared test configuration and fixtures for scihub-cli."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: requires network access (set SCIHUB_CLI_RUN_NETWORK_TESTS=1)"
    )
    config.addinivalue_line(
        "markers", "e2e: requires installed package (set SCIHUB_CLI_RUN_INTEGRATION=1)"
    )
