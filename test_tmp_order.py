
import pytest, os

@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    result = yield
    print("POST-YIELD-MIO", flush=True)
    os._exit(int(exitstatus))

def test_ok():
    assert True
