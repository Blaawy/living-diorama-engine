"""Stage 5: narration. Every sentence is bound to evidence, or it is not said.

No model writes a word. A sentence is a TEMPLATE chosen by the story selector
and filled here from the sealed fact sheet and the measured shots:

    "In the closed city, {avg_duration_s_with_rule:0} seconds."
    "At least {@subjects_visible_min} of them are in this picture."
    "Here. On {$streets.detour.street}."
    "[It|They] [is|are:cars_found_no_other_way] still counted."

    {fact_id:decimals}   a measured number from facts.json, rounded as stated
    {@field}             a measurement of THIS beat's shot, from shots.json
    {$dotted.path}       a string in facts.json (a street name, the prediction)
    [one|many:ref]       grammatical number, chosen by the value of ref

Three kinds of sentence:

* `fact`  states something the fact sheet measured;
* `shot`  states something about the picture, and is bound to what the camera
          planner measured for that very shot;
* `say`   states nothing: a question, a signpost, a pause for breath.

and the rules that make "bound" mean something:

* a NUMERAL may only come from a placeholder. A digit typed into a template is
  refused, and so is a number spelled as a word -- "eighteen people" would
  slip past any check that reads digits;
* a sentence that COMPARES or GENERALISES (longer, fewer, nobody, the same,
  only ...) must carry a CHECK, a relation over evidence that is evaluated
  here and again by the truth audit. A check that does not hold stops the
  pipeline: the narration says something the measurement does not;
* a `say` sentence may contain neither a numeral nor a claim word;
* sentences are short (A1/A2): at most `MAX_WORDS` words each.

The output is the exact text that is spoken and captioned, plus, per sentence,
the evidence it cites and the checks it passed.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import FactoryError
from .util import read_json, seal, verify_seal

NARRATION_SCHEMA = "episode_narration_v1"
MAX_WORDS = 16

_PLACE = re.compile(r"\{([$@]?)([A-Za-z0-9_.]+)(?::(\d))?\}")
_PLURAL = re.compile(r"\[([^\[\]|]*)\|([^\[\]|]*):([$@]?[A-Za-z0-9_.]+)\]")
_DIGIT = re.compile(r"\d")
_WORD = re.compile(r"[A-Za-z']+")

#: Numbers as words. Refused everywhere: a quantity is a numeral from evidence.
NUMBER_WORDS = frozenset("""
zero one two three four five six seven eight nine ten eleven twelve thirteen
fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty
sixty seventy eighty ninety hundred hundreds thousand thousands million dozen
half double twice triple once couple both pair
third thirds quarter quarters halves halved doubled tripled dozens
fifth sixth seventh eighth ninth tenth
""".split())

#: Words that compare, generalise or claim a cause. A sentence using one must
#: carry a check (or state the measured number itself); a `say` sentence may
#: not use one.
CLAIM_WORDS = frozenset("""
longer shorter more fewer less later earlier faster slower quicker bigger
smaller higher lower most least nobody none never always every everyone
everything all empty gone same only right wrong no nothing cannot because
cause causes caused causing made makes proves prove proven forever worse
better worst best increase increased decrease decreased moved
brought led leads thanks results created creates due shows demonstrates
demonstrate worked works went grew grows many single good bad
""".split())

#: Universal claims. A stated number does not carry them ("All 488 trips take
#: longer" states a count, not that every trip did): they need a check.
UNIVERSAL_WORDS = frozenset("all every everyone everything always nobody none nothing forever".split())

OPS = {
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
}

#: Speaking-time estimate, calibrated on the installed engine at rate -1
#: (measured: 2.0-2.5 words/s plus ~0.7 s of file overhead; numerals are slow).
#: It is deliberately a little long: the timeline is planned from it and the
#: real audio must FIT, never the other way round.
EST = {"per_sentence": 0.7, "per_word": 0.36, "per_numeral": 0.5, "per_digit": 0.40,
       "rate_step": 1.10}


class NarrationError(FactoryError):
    stage = "narration"


def _dotted(node: Any, path: str) -> tuple[bool, Any]:
    cur = node
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


#: What the picture HOLDS. When the shot has been rendered these are read from
#: the engine's own measurement (render.json), not from the planner's.
ENGINE_FIELDS = ("subjects_visible_min", "subjects_visible_max", "subjects_visible_last")


def resolve(ref: Any, facts: dict[str, Any], shots: dict[str, Any] | None, beat: str) -> Any:
    """The value of an operand. A reference that does not resolve is a refusal."""
    if not isinstance(ref, str) or not ref.startswith(("fact:", "text:", "shot:", "shot@")):
        return ref                                   # a literal
    if ref.startswith("fact:"):
        row = (facts.get("facts") or {}).get(ref[5:])
        if not isinstance(row, dict) or "value" not in row:
            raise NarrationError("unknown_fact", f"no measured fact {ref[5:]!r}")
        return row["value"]
    if ref.startswith("text:"):
        ok, v = _dotted(facts, ref[5:])
        if not ok or ref[5:].split(".", 1)[0] == "facts":
            raise NarrationError("unknown_fact", f"the fact sheet has no {ref[5:]!r}")
        return v
    if shots is None:
        raise NarrationError("unbound_shot", f"{ref!r} needs the measured shots")
    if ref.startswith("shot@"):
        which, field = ref[5:].split(":", 1)
    else:
        which, field = beat, ref[5:]
    shot = (shots.get("shots") or {}).get(which)
    if shot is None:
        raise NarrationError("unbound_shot", f"beat {which!r} has no measured shot")
    picture = shots.get("_picture")
    if picture is not None and field in ENGINE_FIELDS:
        row = (picture.get("shots") or {}).get(which)
        if row is None or ("engine_" + field) not in row:
            raise NarrationError("unbound_shot", f"beat {which!r} has no engine measurement of {field}")
        return row["engine_" + field]
    ok, v = _dotted(shot, field)
    if not ok:
        raise NarrationError("unbound_shot", f"shot {which!r} measures no {field!r}")
    return v


def _format_number(value: Any, decimals: str | None, where: str) -> tuple[str, int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NarrationError("not_a_number", f"{where} is not a number: {value!r}")
    if isinstance(value, int):
        if decimals not in (None, "0"):
            raise NarrationError("false_precision", f"{where} is a count; it has no decimals")
        return str(value), 0
    if decimals is None:
        raise NarrationError("unstated_precision",
                             f"{where} is a measurement; the template must state its decimals")
    d = int(decimals)
    r = round(float(value), d)
    return (str(int(r)) if d == 0 else f"{r:.{d}f}"), d


def render(template: str, facts: dict[str, Any], shots: dict[str, Any] | None,
           beat: str) -> tuple[str, list[dict[str, Any]]]:
    """Fill a template. Returns (text, citations)."""
    if _DIGIT.search(_PLURAL.sub("", _PLACE.sub("", template))):
        raise NarrationError("unbound_number",
                             f"a numeral is typed into a template instead of bound: {template!r}")
    cites: list[dict[str, Any]] = []

    def plural(m: re.Match) -> str:
        ref = m.group(3)
        full = ("shot:" + ref[1:]) if ref.startswith("@") else ("fact:" + ref)
        v = resolve(full, facts, shots, beat)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise NarrationError("not_a_number", f"grammatical number of {ref!r} needs a number")
        return m.group(1) if round(float(v), 6) == 1 else m.group(2)

    def place(m: re.Match) -> str:
        sigil, name, dec = m.group(1), m.group(2), m.group(3)
        if sigil == "$":
            v = resolve("text:" + name, facts, shots, beat)
            if not isinstance(v, str) or not v.strip():
                raise NarrationError("not_a_string", f"{name!r} is not a sayable string")
            if _DIGIT.search(v):
                raise NarrationError("unbound_number", f"the string {name!r} carries a numeral")
            cites.append({"ref": "text:" + name, "value": v, "stated": v})
            return v
        ref = ("shot:" + name) if sigil == "@" else ("fact:" + name)
        v = resolve(ref, facts, shots, beat)
        stated, d = _format_number(v, dec, ref)
        cites.append({"ref": ref, "value": v, "stated": stated, "decimals": d})
        return stated

    text = _PLACE.sub(place, _PLURAL.sub(plural, template))
    if "{" in text or "}" in text or "[" in text or "]" in text:
        raise NarrationError("bad_template", f"template did not fill cleanly: {template!r}")
    return " ".join(text.split()), cites


def words_of(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def estimate_seconds(text: str, rate: int) -> float:
    """Planned speaking time of one sentence file at SAPI rate `rate`."""
    toks = text.split()
    numerals = [t for t in toks if _DIGIT.search(t)]
    plain = len(toks) - len(numerals)
    s = EST["per_sentence"] + EST["per_word"] * plain
    for n in numerals:
        s += EST["per_numeral"] + EST["per_digit"] * len(_DIGIT.findall(n))
    return round(s * EST["rate_step"] ** (-1 - int(rate)), 3)


def estimate_template_seconds(template: str, rate: int) -> float:
    """Planning-time estimate, before the values are known: a numeral is taken
    as four digits, a string as three words, the longer grammatical form."""
    t = _PLURAL.sub(lambda m: max(m.group(1), m.group(2), key=len), template)
    t = _PLACE.sub(lambda m: "word word word" if m.group(1) == "$" else "0000", t)
    return estimate_seconds(t, rate)


def lint(text: str, kind: str, has_numeric_cite: bool, has_check: bool) -> list[str]:
    """Why this sentence may not be said, if anything."""
    out = []
    ws = words_of(text)
    if not ws:
        out.append("empty")
    if len(ws) > MAX_WORDS:
        out.append(f"too_long:{len(ws)} words (limit {MAX_WORDS})")
    spelled = sorted(set(ws) & NUMBER_WORDS)
    if spelled:
        out.append("number_word:" + ",".join(spelled))
    claims = sorted(set(ws) & CLAIM_WORDS)
    if kind == "say":
        if _DIGIT.search(text):
            out.append("say_with_number")
        if claims:
            out.append("say_with_claim:" + ",".join(claims))
    elif claims and not (has_check or has_numeric_cite):
        out.append("overclaim:" + ",".join(claims))
    elif not has_check and set(ws) & UNIVERSAL_WORDS:
        out.append("overclaim:" + ",".join(sorted(set(ws) & UNIVERSAL_WORDS)))
    return out


def evaluate_check(check: list[Any], facts: dict[str, Any], shots: dict[str, Any] | None,
                   beat: str) -> dict[str, Any]:
    if not isinstance(check, (list, tuple)) or len(check) != 3 or check[1] not in OPS:
        raise NarrationError("bad_check", f"a check is [left, op, right], got {check!r}")
    left, right = resolve(check[0], facts, shots, beat), resolve(check[2], facts, shots, beat)
    try:
        holds = bool(OPS[check[1]](left, right))
    except TypeError:
        raise NarrationError("bad_check", f"{check!r} compares {left!r} with {right!r}")
    return {"left": check[0], "op": check[1], "right": check[2],
            "left_value": left, "right_value": right, "holds": holds}


def bind_narration(story: dict[str, Any], facts: dict[str, Any], shots: dict[str, Any],
                   *, rate: int, picture: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fill, check and seal every sentence of the story. Fails closed.

    With `picture` (the sealed render manifest) every statement about what a
    picture holds is bound to the ENGINE's measurement of that shot. Without it
    the planner's measurement from the record is used and the narration is
    marked `planned`: good for a plan, not for a finished episode.
    """
    if picture is not None:
        if picture.get("shots_hash") != shots.get("shots_hash"):
            raise NarrationError("stale_lineage", "the render was made from different shots")
        shots = {**shots, "_picture": picture}
    if story.get("facts_hash") != facts.get("facts_hash"):
        raise NarrationError("stale_lineage", "the story was selected from a different fact sheet")
    if shots.get("story_hash") != story.get("story_hash") or \
            shots.get("facts_hash") != facts.get("facts_hash"):
        raise NarrationError("stale_lineage", "the shots were planned for a different story")
    lines = []
    seen: set[str] = set()
    for beat in story["beats"]:
        bid = beat["id"]
        if bid not in shots["shots"]:
            raise NarrationError("unbound_shot", f"beat {bid!r} has no measured shot")
        for row in beat["lines"]:
            lid, kind = row["id"], row["kind"]
            if lid in seen:
                raise NarrationError("duplicate_line", f"two sentences share the id {lid!r}")
            seen.add(lid)
            if kind not in ("fact", "shot", "say"):
                raise NarrationError("bad_kind", f"{lid}: unknown sentence kind {kind!r}")
            text, cites = render(row["template"], facts, shots, bid)
            checks = [evaluate_check(c, facts, shots, bid) for c in row.get("checks") or []]
            failed = [c for c in checks if not c["holds"]]
            if failed:
                c = failed[0]
                raise NarrationError(
                    "check_failed",
                    f"{lid}: {text!r} requires {c['left']} {c['op']} {c['right']}, but the "
                    f"evidence gives {c['left_value']!r} and {c['right_value']!r}")
            refs = [c["ref"] for c in cites] + [x for c in checks for x in (c["left"], c["right"])
                                                if isinstance(x, str)]
            on_shot = any(r.startswith("shot") for r in refs)
            on_fact = any(r.startswith(("fact:", "text:")) for r in refs)
            if kind == "say" and (cites or checks):
                raise NarrationError("bad_kind", f"{lid}: a 'say' sentence binds no evidence")
            if kind == "fact" and not on_fact:
                raise NarrationError("unbound_claim", f"{lid}: a 'fact' sentence cites no fact: {text!r}")
            if kind == "shot" and not on_shot:
                raise NarrationError("unbound_claim", f"{lid}: a 'shot' sentence is bound to no "
                                                      f"measurement of its shot: {text!r}")
            problems = lint(text, kind, any("decimals" in c for c in cites), bool(checks))
            if problems:
                raise NarrationError("refused_sentence", f"{lid}: {text!r} -> {problems}")
            est = estimate_seconds(text, rate)
            if est > float(row["planned_seconds"]) + 1e-9:
                raise NarrationError(
                    "outruns_plan", f"{lid}: {text!r} is planned at {row['planned_seconds']} s "
                                    f"but the filled sentence needs {est} s")
            lines.append({"id": lid, "beat": bid, "kind": kind, "text": text,
                          "template": row["template"], "cites": cites, "checks": checks,
                          "words": len(words_of(text)), "planned_seconds": row["planned_seconds"],
                          "gap_after": row["gap_after"],
                          **({"after_event": row["after_event"]} if "after_event" in row else {})})
    n_words = sum(l["words"] for l in lines)
    doc = {
        "schema_version": NARRATION_SCHEMA,
        "facts_hash": facts["facts_hash"],
        "story_hash": story["story_hash"],
        "shots_hash": shots["shots_hash"],
        "render_hash": picture["render_hash"] if picture is not None else None,
        "picture_claims": "engine_confirmed" if picture is not None else "planned",
        "voice_rate": int(rate),
        "rules": {"max_words_per_sentence": MAX_WORDS, "numerals_only_from_evidence": True,
                  "number_words_refused": sorted(NUMBER_WORDS),
                  "claim_words_need_a_check": sorted(CLAIM_WORDS),
                  "universal_words_need_a_check": sorted(UNIVERSAL_WORDS),
                  "written_by": "templates filled from facts.json and shots.json; no model"},
        "lines": lines,
        "counts": {"sentences": len(lines), "words": n_words,
                   "by_kind": {k: sum(1 for l in lines if l["kind"] == k)
                               for k in ("fact", "shot", "say")},
                   "citations": sum(len(l["cites"]) for l in lines),
                   "checks": sum(len(l["checks"]) for l in lines),
                   "mean_words_per_sentence": round(n_words / len(lines), 2) if lines else 0.0,
                   "longest_sentence_words": max((l["words"] for l in lines), default=0)},
        "narration_hash": "",
    }
    return seal(doc, "narration_hash")


def load_narration(path: str | Path) -> dict[str, Any]:
    doc = read_json(path, "narration.json", error=NarrationError)
    if doc.get("schema_version") != NARRATION_SCHEMA:
        raise NarrationError("bad_version", f"narration.json declares {doc.get('schema_version')!r}")
    try:
        verify_seal(doc, "narration_hash", "narration.json")
    except FactoryError as e:
        raise NarrationError("corrupt", e.message)
    return doc
