import json
from pathlib import Path

SPEC = Path(__file__).resolve().parents[3] / "spec" / "test-vectors"


def load_vectors(name: str) -> list:
    return json.loads((SPEC / name).read_text(encoding="utf-8"))["cases"]
