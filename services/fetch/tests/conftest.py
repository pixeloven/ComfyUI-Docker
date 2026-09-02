import pathlib
import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> pathlib.Path:
    return FIXTURES


def pytest_configure(config):
    config.addinivalue_line("markers", "network: hits real hosts on purpose")
