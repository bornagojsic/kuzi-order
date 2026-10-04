"""Shared pytest configuration: custom CLI options."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--slow",
        action="store_true",
        default=False,
        help="Pause 30s between real-API (integration) test cases (free-tier rate-limit friendly).",
    )
