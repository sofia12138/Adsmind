"""Command line entry point for explicit database migrations."""
from __future__ import annotations

import argparse
import json

from migrations.runner import downgrade_one, plan, upgrade_all


def main() -> None:
    parser = argparse.ArgumentParser(description="AdsMind explicit schema migrations")
    parser.add_argument("command", choices=("plan", "upgrade", "downgrade"))
    args = parser.parse_args()
    if args.command == "plan":
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
    elif args.command == "upgrade":
        print(json.dumps({"applied": upgrade_all()}, ensure_ascii=False))
    else:
        print(json.dumps({"rolled_back": downgrade_one()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
