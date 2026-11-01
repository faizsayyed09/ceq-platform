from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.preflight import RuntimePreflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CEQ container role")
    parser.add_argument("role", choices=("api", "worker", "preflight"), nargs="?", default="api")
    args = parser.parse_args(argv)

    if args.role == "preflight":
        result = RuntimePreflight().run(role="preflight")
        print(json.dumps(result, sort_keys=True))
        return 0 if result["passed"] else 1

    if args.role in {"api", "worker"}:
        result = RuntimePreflight().run(role=args.role)
        if not result["passed"]:
            print(json.dumps(result, sort_keys=True), file=sys.stderr)
            return 1

    if args.role in {"api", "worker"}:
        import uvicorn
        uvicorn.run("api.main:app", host="0.0.0.0", port=8000)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
