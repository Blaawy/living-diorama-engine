"""Command line of the factory.

    python -m ldyf.factory run    --brief <brief.json> --out <package dir>
                                  [--no-render] [--no-resume] [--until <stage>] [--shots a,b]
    python -m ldyf.factory verify --package <package dir> [--resimulate]

Exit status 0 on success. A refusal prints `[stage:code] message` and exits 2.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import FactoryError
from .pipeline import STAGES, run_factory, verify_package


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ldyf.factory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run or continue an episode")
    r.add_argument("--brief", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--no-render", action="store_true",
                   help="stop before Unreal: plan, voice, timeline, sound and a partial audit")
    r.add_argument("--no-resume", action="store_true", help="discard the package and start again")
    r.add_argument("--until", choices=STAGES)
    r.add_argument("--shots", help="render only these beats (comma separated), then stop")
    v = sub.add_parser("verify", help="check a finished package and audit it again")
    v.add_argument("--package", required=True)
    v.add_argument("--resimulate", action="store_true",
                   help="also decode the whole episode and run every simulation again (minutes)")
    ns = ap.parse_args(argv)
    try:
        if ns.cmd == "run":
            out = run_factory(ns.brief, ns.out, resume=not ns.no_resume, render=not ns.no_render,
                              until=ns.until, only_shots=ns.shots.split(",") if ns.shots else None,
                              log=lambda s: print(s, flush=True))
        else:
            out = verify_package(ns.package, deep=ns.resimulate, log=lambda s: print(s, flush=True))
    except FactoryError as e:
        print(f"REFUSED {e}", flush=True)
        return 2
    print(json.dumps(out, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
