import argparse
import json
from pathlib import Path

from bank_statement_assistant.adapters.http.app import create_app


class AlwaysReady:
    async def check(self) -> bool:
        return True


def schema() -> dict[str, object]:
    return create_app(readiness=AlwaysReady()).openapi()


def run() -> None:
    parser = argparse.ArgumentParser(description="Write the application OpenAPI contract")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output: Path = args.output
    output.write_text(json.dumps(schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
