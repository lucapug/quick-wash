"""Implementation of the V2 chain probe: prints the sentinel."""

GREETING = "PONTE"


def greeting() -> str:
    return GREETING


def main() -> None:
    print(greeting())
