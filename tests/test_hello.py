import subprocess
import sys

def test_hello_prints_ponte():
    out = subprocess.run(
        [sys.executable, "scripts/hello.py"], capture_output=True, text=True
    ).stdout.strip()
    assert out == "PONTE"
