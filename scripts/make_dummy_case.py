"""Write a new explicit mock case; never overwrite an existing fixture."""
from __future__ import annotations

import argparse
from pathlib import Path

from struct_agent.io.artifacts import write_json
from struct_agent.workflows.mock_case import make_mock_case


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    case = make_mock_case()
    args.out.mkdir(parents=True, exist_ok=False)
    write_json(args.out / "case.json", case.model_dump(mode="json"))
    print(f"Created MOCK ONLY case: {args.out / 'case.json'}")


if __name__ == "__main__":
    main()
