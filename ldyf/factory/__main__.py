"""Command line of the factory.

    python -m ldyf.factory produce --brief <brief.json> --out <package dir>      THE PRODUCT
    python -m ldyf.factory status  --out <package dir>
    python -m ldyf.factory doctor  --brief <brief.json> --out <package dir>
    python -m ldyf.factory verify  --package <package dir> [--resimulate]
    python -m ldyf.factory run     ...                                           (advanced / debugging)

`produce` is the one command: preflight, build or continue, verify, report. Run it again
after any interruption and it carries on. See `produce --help` for the exit codes.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import FactoryError
from .pipeline import STAGES, run_factory, verify_package
from .production import EXIT_CODES, doctor, guard_advanced_run, produce, read_status

_PRODUCE_EPILOG = """\
Give it an episode brief (a small JSON file: a rule, a prediction, a seed) and an output
directory. It checks the machine, simulates the city, builds the story, renders it in
Unreal, speaks and mixes it, audits every sentence against the evidence, and leaves a
verified review package in --out. Open --out/episode.mp4, then contact_sheet.jpg and
truth_audit.json.

If anything stops it - a failure, Ctrl-C, a power cut - run the SAME command again. A
finished package that still verifies is never touched; an unfinished one continues from the
last verified stage. Progress and the last outcome are in <out>.production/ (final_status.json,
journal.jsonl).

What is proven: the factory is exercised end to end on ONE rule configuration - closing block B1B2 of
Baker Avenue at second 30 (ldyf/factory/briefs/close_baker_avenue.json). Other briefs are accepted by the
grammar but are refused by the truth checks (exit 21/22) unless their measurements agree. The default
verification re-derives the text layers and checks reviewer documents and the episode's streams; pictures
and sound are otherwise attested by hash. --deep adds sound/picture/speech/simulation re-derivation.

exit codes:
%s
""" % "\n".join(f"  {v:>3}  {k}" for k, v in sorted(EXIT_CODES.items(), key=lambda kv: (kv[1], kv[0])))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):        # a path with non-cp1252 letters must not crash the summary
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="python -m ldyf.factory",
                                 description="The YouTube factory: one brief in, one verified episode package out.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("produce", help="build, continue or confirm one episode (the production command)",
                       description="Concept/rule brief -> verified episode review package, in one command.",
                       epilog=_PRODUCE_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brief", required=True, help="episode brief JSON (see ldyf/factory/briefs/)")
    p.add_argument("--out", required=True, help="package directory (created; one directory per brief)")
    p.add_argument("--no-render", action="store_true",
                   help="plan only (no Unreal): exits 3, never reports an episode")
    p.add_argument("--status-file", help="also write the machine-readable final status here")
    p.add_argument("--min-free-gb", type=float, default=20.0, help="refuse to start with less free disk (default 20)")
    p.add_argument("--deep", action="store_true",
                   help="also run the DEEP verification (decode, sound and picture against the sealed "
                        "mix and segments, speech re-synthesised, every simulation run again): minutes")
    p.add_argument("--json", action="store_true", help="print only the final status JSON (progress goes to stderr)")
    p.add_argument("--quiet", action="store_true", help="no progress lines")

    s = sub.add_parser("status", help="what happened to a package, and is a run in progress")
    s.add_argument("--out", required=True)

    d = sub.add_parser("doctor", help="check the machine and the output location; change nothing")
    d.add_argument("--brief", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--no-render", action="store_true")
    d.add_argument("--min-free-gb", type=float, default=20.0)

    r = sub.add_parser("run", help="[advanced] run or continue the Phase 4 pipeline stage by stage")
    r.add_argument("--brief", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--no-render", action="store_true",
                   help="stop before Unreal: plan, voice, timeline, sound and a partial audit")
    r.add_argument("--until", choices=STAGES)
    r.add_argument("--shots", help="render only these beats (comma separated), then stop")
    v = sub.add_parser("verify", help="check a finished package and audit it again")
    v.add_argument("--package", required=True)
    v.add_argument("--resimulate", action="store_true",
                   help="also decode the whole episode and run every simulation again (minutes)")
    ns = ap.parse_args(argv)

    if ns.cmd == "produce":
        quiet_to = sys.stderr if ns.json else sys.stdout
        log = (lambda s_: None) if ns.quiet else (lambda s_: print(s_, file=quiet_to, flush=True))
        st = produce(ns.brief, ns.out, render=not ns.no_render, status_path=ns.status_file,
                     min_free_gb=ns.min_free_gb, deep=ns.deep, log=log)
        if ns.json:
            print(json.dumps(st, indent=1, sort_keys=True), flush=True)
        else:
            _print_summary(st)
        return int(st["exit_code"])
    if ns.cmd == "status":
        doc = read_status(ns.out)
        print(json.dumps(doc, indent=1, sort_keys=True), flush=True)
        last = doc.get("last_run") or {}
        if doc.get("run_in_progress"):
            return 4
        code = last.get("exit_code")
        if isinstance(code, int):
            return code
        return 0 if doc.get("package_state") == "marked_finished" else 1
    if ns.cmd == "doctor":
        res = doctor(ns.brief, ns.out, render=not ns.no_render, min_free_gb=ns.min_free_gb)
        print(json.dumps(res, indent=1), flush=True)
        if res["ok"]:
            return 0
        first = next(c for c in res["checks"] if c["status"] == "fail")
        return {"brief_unreadable": 10, "bad_output_path": 12, "output_not_writable": 12, "disk_space": 12,
                "bad_status_path": 12, "foreign_directory": 13, "package_belongs_to_another_brief": 13,
                "already_running": 14}.get(first.get("code"), EXIT_CODES["dependency_missing"])
    try:
        if ns.cmd == "run":
            guard_advanced_run(ns.brief, ns.out)
            out = run_factory(ns.brief, ns.out, resume=True, render=not ns.no_render,
                              until=ns.until, only_shots=ns.shots.split(",") if ns.shots else None,
                              log=lambda s_: print(s_, flush=True))
        else:
            out = verify_package(ns.package, deep=ns.resimulate, log=lambda s_: print(s_, flush=True))
    except FactoryError as e:
        print(f"REFUSED {e}", flush=True)
        return 2
    print(json.dumps(out, indent=1), flush=True)
    return 0


def _print_summary(st: dict) -> None:
    line = "=" * 72
    print(line)
    print(f"{st['outcome'].upper()}  (exit {st['exit_code']}: {st['exit_class']})")
    pk = st["package"]
    if st["exit_code"] == 0:
        print(f"episode : {pk.get('episode')}")
        print(f"length  : {pk.get('seconds')} s, {pk.get('frames')} frames, {pk.get('beats')} beats")
        print(f"package : {pk.get('dir')}  hash {str(pk.get('package_hash'))[:16]}")
        print(f"review  : {', '.join(pk.get('review_first', []))}")
    else:
        print(f"stopped : [{st.get('stage')}:{st.get('code')}] {st.get('message')}")
        print(f"package : {pk.get('dir')} ({pk.get('state_at_end')})")
        print(f"next    : {st.get('advice')}")
    ver = (st.get("verify") or {}).get("verification") or {}
    if ver:
        print(f"verified: {ver.get('level')} level (media attested by hash; --deep re-derives sound, picture, speech)")
    print(f"status  : {pk.get('state_dir')}\\final_status.json")
    print(line)


if __name__ == "__main__":
    sys.exit(main())
