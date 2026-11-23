"""Trial logger (research notes #5: same course, many trials, count every failure).

Each robot run = one row in trials/trials.csv, so we can report results
like "8/9 reached the goal" (see summarise_trials.py, Tuesday).

Use it from another script (for example loop_mission.py):
    from trial_logger import log_trial
    log_trial("E1", "clear", start="lab", goal="lift", reached_goal=True, time_s=42.5)

Plain Python (no ROS), so it runs and tests on a Mac.
"""

import csv
from datetime import datetime
from pathlib import Path

# trials/trials.csv in the repo (this file is in scripts/, so go up one folder)
TRIALS_FILE = Path(__file__).resolve().parent.parent / "trials" / "trials.csv"

# The columns of the CSV, in order
COLUMNS = [
    "trial_id",       # E1-001, E1-002, ... (made automatically)
    "timestamp",      # when the row was written (made automatically)
    "experiment",     # E1 = map + loop and return, E2 = obstacles, ...
    "condition",      # clear / box / low box / blocked
    "start",          # place name, e.g. lab
    "goal",           # place name, e.g. lift
    "max_speed",      # m/s used in this run (Stage 1 = 0.2, Stage 2 = 0.4)
    "builtin_avoid",  # was Unitree's own obstacle avoidance on? (doc section 9)
    "reached_goal",   # yes / no
    "touched",        # did it touch anything? yes / no
    "needed_help",    # did a person have to step in? yes / no
    "gap_cm",         # distance between the end point and the goal (tape on the floor)
    "time_s",         # how long the run took
    "cpu_avg",        # average CPU % from cpu_logger.py (Yuanshu)
    "notes",
]

EXPERIMENTS = ["E1", "E2", "E3", "E4", "E5"]
CONDITIONS = ["clear", "box", "low box", "blocked"]


def yes_no(value):
    """True -> 'yes', False -> 'no', None (not filled in) -> ''."""
    if value is None:
        return ""
    return "yes" if value else "no"


def next_trial_id(experiment, path=TRIALS_FILE):
    """Count earlier rows of the same experiment: E1-001, E1-002, ..."""
    count = 0
    if Path(path).exists():
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row["experiment"] == experiment:
                    count += 1
    return f"{experiment}-{count + 1:03d}"


def log_trial(experiment, condition, start, goal, reached_goal,
              max_speed=None, builtin_avoid=False, touched=None, needed_help=None,
              gap_cm=None, time_s=None, cpu_avg=None, notes="", path=TRIALS_FILE):
    """Add one trial as a new row at the bottom of the CSV. Returns its trial_id."""
    if experiment not in EXPERIMENTS:
        raise ValueError(f"experiment must be one of {EXPERIMENTS}, not '{experiment}'")
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {CONDITIONS}, not '{condition}'")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)   # make trials/ if it's missing
    is_new_file = not path.exists() or path.stat().st_size == 0

    trial_id = next_trial_id(experiment, path)
    row = {
        "trial_id": trial_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "experiment": experiment,
        "condition": condition,
        "start": start,
        "goal": goal,
        "max_speed": max_speed,
        "builtin_avoid": yes_no(builtin_avoid),
        "reached_goal": yes_no(reached_goal),
        "touched": yes_no(touched),
        "needed_help": yes_no(needed_help),
        "gap_cm": gap_cm,
        "time_s": time_s,
        "cpu_avg": cpu_avg,
        "notes": notes,
    }

    with open(path, "a", newline="") as f:           # "a" = append, never overwrite
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if is_new_file:
            writer.writeheader()                     # column names only once, at the top
        writer.writerow(row)
    return trial_id
