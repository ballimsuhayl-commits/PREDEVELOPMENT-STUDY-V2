import re

_ws = re.compile(r"\s+")


def normalize_address(s: str) -> str:
    s = (s or "").strip()
    s = _ws.sub(" ", s)
    return s
