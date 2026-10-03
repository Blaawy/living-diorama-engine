"""Stage 3: select the story. Beats are CHOSEN from measured outcomes, never written to order.

The selector holds a catalogue of candidate beats for a rule class. Each
candidate names

* the CONDITION under which it may be told -- a relation over the sealed fact
  sheet (`cars_found_no_other_way > 0`). A beat whose condition does not hold
  is dropped and the reason is recorded; a consequence that was not measured
  has no beat to be told in;
* its VISUAL: which arm, which subjects, which street, which stretch of
  simulated time, and what the camera must be measured to hold;
* its SENTENCES, as templates bound to facts and to the shot (see
  `ldyf.factory.narration`).

and the selector returns them in a fixed dramatic order built on what holds a
viewer WITHOUT lying to them:

    hook / curiosity gap        a question the record can answer
    prediction before reveal    the sealed prediction is stated, then a pause
    knowable uncertainty        "how much?" -- answerable, and answered later
    prediction error            outcomes nobody declared, taken from the facts
    event boundaries            one beat = one place, one arm, one idea
    signaling and coherence     each beat says where we are and which city
    strategic silence           seconds with no words, over the event itself

A beat's length is planned here from its sentences and its silences, so the
whole timeline is a pure function of the fact sheet: same facts, same story,
byte for byte. The spoken audio must later FIT the plan; it never stretches it.

Fails closed: an episode that cannot fill the required structure, or whose
honest length falls outside the brief's target, is refused -- it is not padded.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from . import FactoryError
from .narration import NarrationError, estimate_seconds, render
from .util import read_json, seal, verify_seal

STORY_SCHEMA = "episode_story_v1"

#: Pacing. Stated, written into story.json, the same for every beat.
PACING = {
    "lead_in_seconds": 1.0,        # picture before the first word of a beat
    "sentence_gap_seconds": 0.6,   # breath between sentences (A1/A2 listeners)
    "event_watch_seconds": 2.0,    # silence before a narrated event happens on screen
    "event_settle_seconds": 1.5,   # silence after it, before the next word
}

REQUIRED_DEVICES = ("hook", "curiosity_gap", "prediction_before_reveal", "knowable_uncertainty",
                    "prediction_error", "signaling", "strategic_silence", "reveal")

_AT = re.compile(r"\{@[A-Za-z0-9_.]+\}")
_PLURAL_AT = re.compile(r"\[([^\[\]|]*)\|([^\[\]|]*):@[A-Za-z0-9_.]+\]")


class StoryError(FactoryError):
    stage = "story"


def L(template: str, kind: str = "say", checks: list | None = None, gap: float | None = None,
      after_event: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {"template": template, "kind": kind}
    if checks:
        row["checks"] = checks
    if gap is not None:
        row["gap"] = float(gap)
    if after_event:
        row["after_event"] = True
    return row


def _planned_seconds(template: str, facts: dict[str, Any], rate: int) -> float:
    """Speaking time of a template with its FACT values in and shot values assumed long."""
    t = _PLURAL_AT.sub(lambda m: max(m.group(1), m.group(2), key=len), template)
    t = _AT.sub("ATSHOTVALUE", t)
    try:
        text, _ = render(t, facts, None, "")
    except NarrationError as e:
        raise StoryError("unbound_sentence", f"{template!r}: {e.message}")
    return estimate_seconds(text.replace("ATSHOTVALUE", "000"), rate)


# --- the closure catalogue -------------------------------------------------------

def _closure_candidates(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Candidate beats for an edge closure, in telling order."""
    F = {k: v["value"] for k, v in doc["facts"].items()}
    streets = doc.get("streets") or {}
    stuck = doc.get("stuck_cars") or {}
    groups = doc.get("groups") or {}
    at = float(F["rule_second"])
    has = lambda *names: all(n in streets for n in names)          # noqa: E731
    out: list[dict[str, Any]] = []

    def beat(bid: str, role: str, devices: list[str], when: bool, why: str, visual: dict,
             lines: list, hold: float, event: dict | None = None) -> None:
        out.append({"id": bid, "role": role, "devices": devices, "when": bool(when), "why": why,
                    "visual": visual, "lines": lines, "hold": float(hold),
                    **({"event": event} if event else {})})

    cars_seen = [">=", 1]
    # 1 ------------------------------------------------------------------ hook
    beat("hook", "hook", ["hook", "curiosity_gap", "signaling"],
         F["cars_on_closed_block_without_rule"] > 0,
         "cars are recorded on the block the rule closes, in the arm without the rule",
         {"kind": "street", "arm": "baseline", "street": "closed", "style": "eye",
          "subjects": {"group": "cars_on_closed_block"}, "on_street": "lanes",
          "window": {"mode": "best", "t_min": at + 10.0, "t_max": 225.0},
          "require": {"min_visible": 1, "fraction": 0.4}},
         [L("This is {$streets.closed.street}.", "fact"),
          L("It is a street in a small city."),
          L("Cars drive here.", "shot", [["shot:subjects_visible_max", ">=", 1]]),
          L("Today we close {blocks_closed} [block|blocks:blocks_closed] of it.", "fact"),
          L("What happens to the city?", gap=1.0)],
         hold=3.0)
    # 2 --------------------------------------------------------------- promise
    beat("promise", "setup", ["curiosity_gap", "signaling"], has("main"),
         "a busiest street that is neither the closed one nor the detour was measured",
         {"kind": "street", "arm": "baseline", "street": "main", "style": "high",
          "subjects": {"group": "vehicles"}, "on_street": True,
          "window": {"mode": "best", "t_min": 300.0, "t_max": 620.0},
          "require": {"min_visible": 2, "fraction": 0.7}},
         [L("We did not guess."),
          L("We built this city in a computer."),
          L("Then we ran it {arms_run} times.", "fact"),
          L("First with the street open."),
          L("Then with the street closed."),
          L("Each run uses the same random numbers.", "fact", [["fact:seeds_used", "==", 1]])],
         hold=3.0)
    # 3 ----------------------------------------------------------------- world
    beat("world", "setup", ["signaling"], has("destination") and F["walkers_followed"] > 0,
         "the world has followed walkers and a street they walk to",
         {"kind": "street", "arm": "baseline", "street": "destination", "style": "eye",
          "subjects": {"group": "people"}, "on_street": True,
          "window": {"mode": "best", "t_min": 620.0, "t_max": 900.0},
          "require": {"min_visible": 2, "fraction": 0.7}},
         [L("Here is the open city."),
          L("{cars_recorded_without_rule} cars make a trip.", "fact"),
          L("{people_recorded_without_rule} people walk.", "fact"),
          L("We follow {walkers_followed} of the walkers closely.", "fact"),
          L("They have a yellow ball over the head.", "shot",
            [["shot:marks.yellow.group", "==", "walkers"],
             ["shot:marks.yellow.count", "==", "fact:walkers_followed"]]),
          L("These {walkers_followed} can change their plan.", "fact"),
          L("The other {other_people} people walk a fixed path.", "fact")],
         hold=2.0)
    # 4 ------------------------------------------------------------------ rule
    beat("rule", "setup", ["signaling"], True, "every episode has a rule",
         {"kind": "same_as", "same_as": "hook", "arm": "ruled",
          "subjects": {"group": "vehicles"}, "on_street": "lanes",
          "require": {"max_visible": 0}},
         [L("At second {rule_second:0}, we close this block to cars.", "fact"),
          L("It is the way from {$streets.closed.from} to {$streets.closed.to}.", "fact"),
          L("Only this direction closes.", "fact", [["fact:opposite_direction_open", "==", True]]),
          L("This is the closed city, at the same minute.", "shot",
            [["shot:arm", "==", "ruled"], ["shot:sim_start", "==", "shot@hook:sim_start"],
             ["shot:camera.same_camera_as", "==", "hook"]]),
          L("After second {rule_second:0}, {cars_on_closed_block_with_rule} cars drive on the closed side.",
            "fact"),
          L("The closed side in this picture has no car on it.", "shot",
            [["shot:subjects_visible_max", "==", 0]]),
          L("{cars_on_open_side_with_rule} cars drive the other way.", "fact")],
         hold=2.0)
    # 5 ------------------------------------------------------------ prediction
    beat("prediction", "prediction", ["prediction_before_reveal", "knowable_uncertainty",
                                      "strategic_silence"],
         F["prediction_declared_before_run"] is True and has("jam"),
         "the sealed rule manifest carries a prediction declared before the run",
         {"kind": "street", "arm": "baseline", "street": "jam", "style": "eye",
          "subjects": {"group": "vehicles"}, "on_street": True,
          "window": {"mode": "best", "t_min": 60.0, "t_max": 300.0},
          "require": {"min_visible": 1, "fraction": 0.5}},
         [L("Before the run, we wrote down a guess.", "fact",
            [["fact:prediction_declared_before_run", "==", True]]),
          L("{$prediction.text}", "fact", [["fact:prediction_declared_before_run", "==", True]]),
          L("But how big is the change?"),
          L("And what about the people who walk?"),
          L("Make your guess now.")],
         hold=5.0)
    # 6 ---------------------------------------------------------------- replan
    beat("replan", "event", ["signaling"],
         F.get("walkers_changed_route", 0) > 0 and "first_route_change_second" in F,
         "followed walkers replanned around the closed street",
         {"kind": "group", "arm": "ruled", "style": "high",
          "subjects": {"group": "treatment"},
          "window": {"mode": "fixed", "start": float(math.floor(max(at - 6.0, 0.0)))},
          "require": {"min_visible": 1, "fraction": 0.6}},
         [L("Second {rule_second:0}. The block closes.", "fact"),
          L("{walkers_planned_through} of our {walkers_followed} walkers planned to use {$streets.closed.street}.",
            "fact"),
          L("In this model, the first of them knows in the same second.", "fact",
            [["fact:first_route_change_second", "==", "fact:rule_second"]]),
          L("By second {last_route_change_second:0}, {walkers_changed_route} walkers have a new plan.",
            "fact"),
          L("Some of them are in this picture.", "shot", [["shot:subjects_visible_min", ">=", 1]])],
         hold=1.5)
    # 7 ---------------------------------------------------------------- before
    beat("walkers_before", "evidence", ["signaling", "strategic_silence"],
         F.get("walkers_seen_on_closed_street_without_rule", 0) > 0,
         "followed walkers are recorded on the closed street in the arm without the rule",
         {"kind": "street", "arm": "baseline", "street": "closed", "style": "eye",
          "subjects": {"group": "treatment"}, "on_street": True,
          "window": {"mode": "best", "t_min": 230.0, "t_max": 400.0},
          "require": {"min_visible": 3, "fraction": 0.9}},
         [L("First, the open city."),
          L("These are our walkers on {$streets.closed.street}.", "fact"),
          L("At least {@subjects_visible_min} of them are in the picture the whole time.", "shot"),
          L("On average, a walker spends {seconds_on_closed_street_without_rule:0} seconds on this block.",
            "fact")],
         hold=5.0)
    # 8 ----------------------------------------------------------------- after
    beat("walkers_after", "reveal", ["reveal", "signaling", "strategic_silence"],
         F.get("walkers_seen_on_closed_street_without_rule", 0) > 0
         and F.get("walkers_seen_on_closed_street_with_rule", 1) == 0,
         "no followed walker is recorded on the closed street in the arm with the rule",
         {"kind": "same_as", "same_as": "walkers_before", "arm": "ruled",
          "subjects": {"group": "walkers"}, "on_street": True,
          "require": {"max_visible": 0}},
         [L("Now the closed city."),
          L("It is the same camera and the same minute.", "shot",
            [["shot:camera.same_camera_as", "==", "walkers_before"],
             ["shot:sim_start", "==", "shot@walkers_before:sim_start"],
             ["shot:arm", "==", "ruled"]]),
          L("{walkers_seen_on_closed_street_with_rule} of our walkers come here.", "fact"),
          L("{@subjects_visible_max} of them are in this picture.", "shot",
            [["shot:subjects_visible_max", "==", 0]]),
          L("Any people you see are other people.", "fact", [["fact:other_people", ">", 0]])],
         hold=4.0)
    # 9 ---------------------------------------------------------------- detour
    beat("detour", "reveal", ["reveal", "signaling"],
         has("detour") and F.get("seconds_on_detour_street_with_rule", 0) > 0,
         "the followed walkers' time moved to another street",
         {"kind": "street", "arm": "ruled", "street": "detour", "style": "eye",
          "subjects": {"group": "treatment"}, "on_street": True,
          "window": {"mode": "best", "t_min": 200.0, "t_max": 360.0},
          "require": {"min_visible": 3, "fraction": 0.9}},
         [L("So where are our walkers?"),
          L("Here. On {$streets.detour.street}.", "fact"),
          L("At least {@subjects_visible_min} of them are in this picture.", "shot"),
          L("In the open city, they spend {seconds_on_detour_street_without_rule:0} seconds on this block.",
            "fact"),
          L("In the closed city, {seconds_on_detour_street_with_rule:0} seconds.", "fact")],
         hold=4.0)
    # 10 ------------------------------------------------------- detour, before
    beat("detour_before", "evidence", ["signaling"],
         has("detour") and F.get("seconds_on_detour_street_with_rule", 0) > 0
         and F.get("seconds_on_detour_street_without_rule", 1) == 0,
         "the same street holds none of them in the arm without the rule",
         {"kind": "same_as", "same_as": "detour", "arm": "baseline",
          "subjects": {"group": "treatment"}, "on_street": True,
          "require": {"max_visible": 0}},
         [L("This is the same block in the open city.", "shot",
            [["shot:arm", "==", "baseline"], ["shot:camera.same_camera_as", "==", "detour"]]),
          L("{@subjects_visible_max} of our walkers are here.", "shot",
            [["shot:subjects_visible_max", "==", 0]]),
          L("The rule moved them to another street.", "fact",
            [["fact:seconds_on_detour_street_with_rule", ">",
              "fact:seconds_on_detour_street_without_rule"],
             ["fact:seconds_on_closed_street_with_rule", "<",
              "fact:seconds_on_closed_street_without_rule"]])],
         hold=2.0)
    # 11 --------------------------------------------------------------- arrive
    later, earlier = F.get("walkers_arrived_later", 0), F.get("walkers_arrived_earlier", 0)
    mean_later = F.get("trip_time_change_mean_s", 0.0)
    arrive = [L("Their new path is up to {path_shift_max_m:0} metres away from the old path.", "fact"),
              L("Are they late?", gap=3.0)]
    if mean_later > 0:
        arrive.append(L("On average, they arrive {trip_time_change_mean_s:0} seconds later.", "fact",
                        [["fact:trip_time_change_mean_s", ">", 0]]))
    arrive.append(L("{walkers_arrived_later} [walker|walkers:walkers_arrived_later] "
                    "[is|are:walkers_arrived_later] later.", "fact"))
    if earlier > 0:
        arrive.append(L("But {walkers_arrived_earlier} [walker|walkers:walkers_arrived_earlier] "
                        "[is|are:walkers_arrived_earlier] earlier.", "fact"))
        arrive.append(L("The biggest saving is {trip_time_change_max_earlier_s:0} seconds.", "fact"))
        arrive.append(L("Did you guess that?"))
    beat("arrive", "surprise", ["prediction_error", "knowable_uncertainty", "strategic_silence"],
         has("destination") and (later + earlier) > 0 and "path_shift_max_m" in F,
         "the followed walkers' arrival times differ between the arms",
         {"kind": "street", "arm": "ruled", "street": "destination", "style": "eye",
          "subjects": {"group": "treatment"}, "on_street": True,
          "window": {"mode": "best", "t_min": 300.0, "t_max": 620.0},
          "require": {"min_visible": 1, "fraction": 0.6}},
         arrive, hold=3.0)
    # 12 -------------------------------------------------------------- control
    beat("control", "evidence", ["signaling"],
         F.get("walkers_not_through", 0) > 0 and "control_path_shift_m" in F and has("control_path"),
         "some followed walkers never planned to use the closed street",
         {"kind": "street", "arm": "ruled", "style": "eye", "street": "control_path",
          "subjects": {"group": "control"}, "on_street": "street",
          "window": {"mode": "best", "t_min": 60.0, "t_max": 700.0},
          "require": {"min_visible": 1, "fraction": 0.6}},
         [L("{walkers_not_through} of our walkers did not plan to use {$streets.closed.street}.", "fact"),
          L("They are our check."),
          L("Their path moves by {control_path_shift_m:1} metres at most.", "fact"),
          L("Some of them are in this picture.", "shot", [["shot:subjects_visible_min", ">=", 1]])],
         hold=2.0)
    # 13 ------------------------------------------------------- cars, rerouted
    beat("cars_rerouted", "evidence", ["signaling"],
         F.get("cars_rerouted", 0) > 0 and bool(groups.get("cars_rerouted")),
         "vehicles were re-routed off the closed block",
         {"kind": "street", "arm": "ruled", "street": "main", "style": "eye",
          "subjects": {"group": "cars_rerouted"}, "on_street": False, "mark_subjects": True,
          "window": {"mode": "best", "t_min": 60.0, "t_max": 290.0},
          "require": {"min_visible": 1, "fraction": 0.3}},
         [L("Now the cars."),
          L("In the open city, {cars_on_closed_block_without_rule} cars use the block after second "
            "{rule_second:0}.", "fact"),
          L("In the closed city, {cars_asked_to_reroute} cars need a new way.", "fact"),
          L("{cars_rerouted} of them find it.", "fact"),
          L("Up to {@subjects_visible_max} of them [is|are:@subjects_visible_max] in this picture, "
            "with a red ball.", "shot", [["shot:marks.red.group", "==", "cars_rerouted"]])],
         hold=2.0)
    # 14 ---------------------------------------------------------------- stuck
    first = next(iter(stuck), None)
    if first is not None:
        row = stuck[first]
        beat("stuck", "surprise", ["prediction_error", "strategic_silence"],
             F.get("cars_found_no_other_way", 0) > 0,
             "vehicles stood still for the simulator's whole teleport limit",
             {"kind": "group", "arm": "ruled", "style": "eye", "street": row["edge"],
              "subjects": {"group": "stuck_cars", "uids": [first]}, "mark_subjects": True,
              "window": {"mode": "fixed", "start": float(math.ceil(row["from_s"] + 40.0))},
              "require": {"min_visible": 1, "fraction": 1.0, "stopped": True}},
             [L("But {cars_found_no_other_way} cars find no other way.", "fact"),
              L("This is the first of them. It has a red ball.", "shot",
                [["shot:subjects.count", "==", 1], ["shot:marks.red.count", "==", 1]]),
              L("Its way goes through the closed block.", "fact",
                [["fact:cars_found_no_other_way", ">", 0]]),
              L("It stands still.", "shot", [["shot:subjects_speed_max_mps", "<", 0.1]])],
             hold=6.0)
        # 15 --------------------------------------------------------- teleport
        beat("moved", "surprise", ["prediction_error", "strategic_silence", "reveal"],
             F.get("cars_teleported_with_rule", 0) > 0 and F.get("cars_found_no_other_way", 0) > 0,
             "the simulator itself removed stuck vehicles",
             {"kind": "group", "arm": "ruled", "style": "high", "street": row["edge"],
              "subjects": {"group": "stuck_cars", "uids": [first]}, "mark_subjects": True,
              "window": {"mode": "event", "event_second": row["to_s"]},
              "require": {"min_visible": 1, "until": row["to_s"], "then_absent": True}},
             [L("It stands for {teleport_limit_s:0} seconds. That is {teleport_limit_minutes:0} minutes.",
                "fact"),
              L("Then the computer takes it off the street.", "fact",
                [["fact:cars_teleported_with_rule", ">", 0]]),
              L("Watch."),
              L("It is gone.", "shot", [["shot:subjects_visible_last", "==", 0]], after_event=True),
              L("This happens {cars_teleported_with_rule} times in the closed city.", "fact"),
              L("In the open city, {cars_teleported_without_rule} times.", "fact"),
              L("We count these cars as finished trips.", "fact",
                [["fact:cars_not_finished_with_rule", "==", 0]])],
             hold=2.0, event={"second": row["to_s"], "what": "the simulator removes the stuck car",
                              "subject": first})
    # 16 -------------------------------------------------------- never started
    beat("never_started", "surprise", ["prediction_error"],
         F.get("cars_never_started", 0) > 0,
         "vehicles whose trip begins on the closed block were never inserted",
         {"kind": "street", "arm": "baseline", "street": "closed", "style": "high",
          "subjects": {"group": "cars_never_started"}, "on_street": "lanes", "mark_subjects": True,
          "window": {"mode": "best", "t_min": 405.0, "t_max": 560.0},
          "require": {"min_visible": 1, "fraction": 0.1}},
         [L("And {cars_never_started} cars never start.", "fact"),
          L("Their trip begins on the closed block.", "fact", [["fact:cars_never_started", ">", 0]]),
          L("In the open city, such a car is in this picture, with a red ball.", "shot",
            [["shot:subjects_visible_max", ">=", 1], ["shot:arm", "==", "baseline"],
             ["shot:marks.red.group", "==", "cars_never_started"]]),
          L("In the closed city, it is not in the record.", "fact",
            [["fact:cars_recorded_with_rule", "<", "fact:cars_recorded_without_rule"]]),
          L("{trips_completed_without_rule:0} car trips become {trips_completed_with_rule:0}.", "fact")],
         hold=2.0)
    # 17 --------------------------------------------------------------- reveal
    metric = (doc.get("prediction") or {}).get("metric")
    confirmed = F["prediction_outcome"] == "confirmed"
    if metric == "avg_duration_s":
        more = F["avg_duration_s_direction"] == "increase"
        reveal = [L("Now, back to our guess."),
                  L("{$prediction.text}", "fact",
                    [["fact:prediction_declared_before_run", "==", True]]),
                  L("In the open city, a car trip takes {avg_duration_s_without_rule:0} seconds on average.",
                    "fact"),
                  L("In the closed city, {avg_duration_s_with_rule:0} seconds.", "fact", gap=1.5),
                  L("That is {avg_duration_s_change:0} seconds " + ("more." if more else "less."), "fact",
                    [["fact:avg_duration_s_with_rule", ">" if more else "<",
                      "fact:avg_duration_s_without_rule"]]),
                  L("It is a change of {avg_duration_s_change_percent:0} percent.", "fact"),
                  L("Our guess was right." if confirmed else "Our guess was wrong.", "fact",
                    [["fact:prediction_outcome", "==", "confirmed" if confirmed else "contradicted"]])]
        beat("reveal", "reveal", ["reveal", "prediction_before_reveal", "signaling"], has("main"),
             "the predicted metric was measured in both arms",
             {"kind": "same_as", "same_as": "promise", "arm": "ruled",
              "subjects": {"group": "vehicles"}, "on_street": True,
              "require": {"min_visible": 1, "fraction": 0.5}},
             reveal, hold=3.0)
    # 18 ---------------------------------------------------------------- twist
    beat("waiting", "surprise", ["prediction_error", "reveal"],
         F.get("waiting_share_of_extra_time_percent", 0) > 50 and has("jam")
         and F.get("avg_route_length_m_direction") == "increase",
         "most of the extra trip time is waiting time, not distance",
         {"kind": "street", "arm": "ruled", "street": "jam", "style": "high",
          "subjects": {"group": "vehicles"}, "on_street": True,
          "window": {"mode": "best", "t_min": 395.0, "t_max": 690.0},
          "require": {"min_visible": 2, "fraction": 0.8}},
         [L("But look at where the time goes."),
          L("The trips are only {avg_route_length_m_change:0} metres longer.", "fact",
            [["fact:avg_route_length_m_with_rule", ">", "fact:avg_route_length_m_without_rule"]]),
          L("The waiting is {avg_waiting_time_s_change:0} seconds longer.", "fact",
            [["fact:avg_waiting_time_s_with_rule", ">", "fact:avg_waiting_time_s_without_rule"]]),
          L("{waiting_share_of_extra_time_percent:0} percent of the extra time is waiting.", "fact"),
          L("Cars wait at this corner.", "shot", [["shot:subjects_stopped_max", ">=", 1]])]
         # said only when such cars were measured
         + ([L("The {cars_found_no_other_way} stuck cars are in this average.", "fact")]
            if F.get("cars_found_no_other_way", 0) > 0 else [])
         # the cars that never started are missing from one side of the comparison only
         + ([L("The {cars_never_started} cars that never start are not.", "fact",
               [["fact:trips_completed_with_rule", "<", "fact:trips_completed_without_rule"]])]
            if F.get("cars_never_started", 0) > 0 else []),
         hold=4.0)
    # 19 ----------------------------------------------------------- replicates
    if "all_runs" in F:
        beat("repeats", "evidence", ["knowable_uncertainty", "signaling"], F["all_runs"] > 1,
             "the episode was repeated with other seeds",
             {"kind": "street", "arm": "ruled", "street": "closed", "style": "high",
              "subjects": {"group": "other_people"}, "on_street": True,
              "window": {"mode": "best", "t_min": 420.0, "t_max": 700.0},
              "require": {"min_visible": 1, "fraction": 0.6}},
             [L("Was it luck?"),
              L("We ran the city {repeat_runs} more times, with other random numbers.", "fact"),
              L("The result points the same way in {all_runs_same_direction} of {all_runs} runs.",
                "fact"),
              L("That is a small test. It is not proof.")],
             hold=2.0)
    # 20 --------------------------------------------------------------- limits
    beat("limits", "honesty", ["signaling"], True, "every episode states its limits",
         {"kind": "street", "arm": "ruled", "street": "destination", "style": "high",
          "subjects": {"group": "people"}, "on_street": True,
          "window": {"mode": "best", "t_min": 640.0, "t_max": 900.0},
          "require": {"min_visible": 1, "fraction": 0.6}},
         [L("Now the limits."),
          L("This is a model. It is not a real city."),
          L("Our walkers follow a simple rule: stay off a closed street.", "fact",
            [["text:agent_policy.policy", "==", "avoid_whole_street"]]),
          L("The walkers stay away because we told them to.", "fact",
            [["text:agent_policy.policy", "==", "avoid_whole_street"]]),
          L("And we follow only {walkers_followed} walkers.", "fact")],
         hold=2.0)
    # 21 ---------------------------------------------------------------- close
    close = [L("So. {blocks_closed} closed [block|blocks:blocks_closed].", "fact"),
             L("{walkers_changed_route} walkers changed their path.", "fact")]
    if F.get("cars_rerouted", 0) > 0:
        close.append(L("{cars_rerouted} cars found another way.", "fact"))
    if F.get("cars_found_no_other_way", 0) > 0:
        close.append(L("{cars_found_no_other_way} did not.", "fact"))
    if F.get("cars_never_started", 0) > 0:
        close.append(L("{cars_never_started} never started.", "fact"))
    close.append(L("The open city was done after {city_busy_minutes_without_rule:0} minutes, "
                   "the closed city after {city_busy_minutes_with_rule:0}.", "fact"))
    close.append(L("What would you close next?"))
    beat("close", "close", ["signaling", "curiosity_gap", "strategic_silence"], True,
         "every episode closes on its measured results",
         {"kind": "street", "arm": "baseline", "street": "closed", "style": "high",
          "subjects": {"group": "cars_on_closed_block"}, "on_street": "lanes",
          "window": {"mode": "best", "t_min": 560.0, "t_max": 720.0},
          "require": {"min_visible": 1, "fraction": 0.3}},
         close, hold=5.0)
    return out


CATALOGUES = {"edge_closure": _closure_candidates}


# --- the selector -----------------------------------------------------------------

def _finish_beat(cand: dict[str, Any], facts: dict[str, Any], rate: int) -> dict[str, Any]:
    """Plan a selected beat's sentences and its length."""
    P = PACING
    lines = []
    t = P["lead_in_seconds"]
    event_offset = None
    for i, row in enumerate(cand["lines"]):
        planned = _planned_seconds(row["template"], facts, rate)
        gap = float(row.get("gap", P["sentence_gap_seconds"]))
        out = {"id": f"{cand['id']}.{i + 1:02d}", "template": row["template"], "kind": row["kind"],
               "planned_seconds": planned, "gap_after": gap}
        if row.get("checks"):
            out["checks"] = row["checks"]
        if row.get("after_event"):
            if "event" not in cand:
                raise StoryError("bad_beat", f"beat {cand['id']!r} has a sentence after an event "
                                             "but names no event")
            if event_offset is None:
                start = math.floor(float(cand["event"]["second"]) - (t + P["event_watch_seconds"]))
                event_offset = round(float(cand["event"]["second"]) - start, 3)
                t = event_offset + P["event_settle_seconds"]
            out["after_event"] = P["event_settle_seconds"]
        lines.append(out)
        t += planned + gap
    seconds = float(math.ceil(t + cand["hold"]))
    visual = dict(cand["visual"])
    beat = {"id": cand["id"], "role": cand["role"], "devices": cand["devices"], "why": cand["why"],
            "seconds": seconds, "hold_seconds": cand["hold"], "lines": lines, "visual": visual}
    if "event" in cand:
        if event_offset is None:
            raise StoryError("bad_beat", f"beat {cand['id']!r} names an event no sentence waits for")
        ev = dict(cand["event"])
        ev["offset_seconds"] = event_offset
        beat["event"] = ev
        if visual["window"].get("mode") == "event":
            visual["window"] = {"mode": "fixed", "start": float(round(ev["second"] - event_offset))}
    return beat


def select_story(facts: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    """The sealed story for one fact sheet, or a refusal."""
    kind = facts.get("rule_change_type")
    catalogue = CATALOGUES.get(kind)
    if catalogue is None:
        raise StoryError("no_catalogue", f"no beat catalogue exists for a {kind!r} rule; the factory "
                                         f"tells {sorted(CATALOGUES)} episodes")
    try:
        cands = catalogue(facts)
    except KeyError as e:
        raise StoryError("missing_evidence", f"the fact sheet lacks {e} which the story needs")
    rate = int(brief["voice_rate"])
    selection, beats = [], []
    for c in cands:
        selection.append({"beat": c["id"], "selected": c["when"], "condition": c["why"]})
        if c["when"]:
            beats.append(_finish_beat(c, facts, rate))
    ids = [b["id"] for b in beats]
    if len(set(ids)) != len(ids):
        raise StoryError("bad_catalogue", "two beats share an id")
    # a comparison shot needs the shot it is compared with
    for b in beats:
        ref = b["visual"].get("same_as")
        if ref is not None:
            if ref not in ids:
                raise StoryError("incomplete_story", f"beat {b['id']!r} compares itself with "
                                                     f"{ref!r}, which was not selected")
            if ids.index(ref) > ids.index(b["id"]):
                raise StoryError("incomplete_story", f"beat {b['id']!r} is told before {ref!r}, "
                                                     "the shot it is compared with")
    structure = {d: [b["id"] for b in beats if d in b["devices"]] for d in REQUIRED_DEVICES}
    lacking = [d for d, bs in structure.items() if not bs]
    if lacking:
        raise StoryError("structure_incomplete",
                         f"the measured outcomes cannot fill {lacking}: there is no honest episode "
                         "to tell from this fact sheet")
    roles = [b["role"] for b in beats]
    if "prediction" not in roles or "reveal" not in ids:
        raise StoryError("structure_incomplete", "the episode needs a prediction and its reveal")
    if roles.index("prediction") > ids.index("reveal"):
        raise StoryError("structure_incomplete", "the reveal would come before the prediction")
    if beats[0]["role"] != "hook":
        raise StoryError("structure_incomplete", "the episode does not open on its hook")
    silent = [b["id"] for b in beats if b["hold_seconds"] >= 3.0]
    total = sum(b["seconds"] for b in beats)
    lo, hi = brief["target_seconds"]
    if not lo <= total <= hi:
        raise StoryError(
            "length_out_of_range",
            f"the beats this fact sheet supports run {total:.0f} s; the brief asks for "
            f"{lo:.0f}-{hi:.0f} s. The factory does not pad and does not cut measured beats")
    spoken = sum(l["planned_seconds"] for b in beats for l in b["lines"])
    doc = {
        "schema_version": STORY_SCHEMA,
        "facts_hash": facts["facts_hash"],
        "brief_sha256": facts["brief_sha256"],
        "rule_change_type": kind,
        "title": brief["title"],
        "voice_rate": rate,
        "pacing": PACING,
        "selection": selection,
        "structure": {**structure, "event_boundaries": ids, "silent_holds": silent},
        "beats": beats,
        "seconds_total": total,
        "seconds_planned_speech": round(spoken, 2),
        "seconds_without_words": round(total - spoken, 2),
        "story_hash": "",
    }
    return seal(doc, "story_hash")


def load_story(path: str | Path) -> dict[str, Any]:
    doc = read_json(path, "story.json", error=StoryError)
    if doc.get("schema_version") != STORY_SCHEMA:
        raise StoryError("bad_version", f"story.json declares {doc.get('schema_version')!r}")
    try:
        verify_seal(doc, "story_hash", "story.json")
    except FactoryError as e:
        raise StoryError("corrupt", e.message)
    return doc
