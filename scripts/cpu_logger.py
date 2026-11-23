#!/usr/bin/env python3
"""CPU and memory logger for trials (research notes #5, owner: Yuanshu).

Once per second, writes the whole-machine CPU % and the CPU % and memory of
every watched process (slam_toolbox, Nav2, AMCL, Livox driver, our scripts...)
to a CSV. When it stops (Ctrl+C or --duration), it prints the averages. The
average whole-machine CPU is the number that goes into cpu_avg in
trials/trials.csv.

Usage (start it just before the trial, stop it right after):
    python3 cpu_logger.py --trial-id E1-001            # until Ctrl+C
    python3 cpu_logger.py --trial-id E1-001 --duration 120
    python3 cpu_logger.py --all                        # every process, not only ROS ones
    python3 cpu_logger.py --dry-run --duration 3       # print, write no file

Output: trials/cpu/<trial-id>.csv with columns
    timestamp, elapsed_s, scope, pid, name, cpu_percent, mem_mb
scope = "system" (one row per second, whole machine; cpu_percent is 0-100 %
over all cores) or "process" (one row per watched process; cpu_percent is
per core, so 200 % = two full cores, like `top`).

From another script (for example loop_mission.py):
    from cpu_logger import cpu_avg_from_csv
    log_trial(..., cpu_avg=cpu_avg_from_csv("trials/cpu/E1-001.csv"))

Needs psutil (pip install psutil, or apt install python3-psutil). The pure
functions below do not, so the tests run on a Mac without it.
"""

import argparse
import csv
import signal
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CPU_DIR = Path(__file__).resolve().parent.parent / "trials" / "cpu"

COLUMNS = ["timestamp", "elapsed_s", "scope", "pid", "name", "cpu_percent", "mem_mb"]

# A process is watched if its name or command line contains one of these.
DEFAULT_PATTERNS = [
    "slam_toolbox", "amcl", "map_server", "controller_server", "planner_server",
    "behavior_server", "bt_navigator", "waypoint_follower", "velocity_smoother",
    "collision_monitor", "lifecycle_manager", "pointcloud_to_laserscan",
    "scan_to_scan_filter", "livox", "foxglove", "static_transform",
    "odom_publisher", "cmd_vel_bridge", "loop_mission", "go_to", "where_am_i",
    "ros2", "rviz",
]


def matches(name, cmdline, patterns):
    """True if any pattern is in the process name or its command line."""
    text = f"{name} {cmdline}".lower()
    return any(p.lower() in text for p in patterns)


def short_name(name, cmdline):
    """A readable label: for 'python3 scripts/go_to.py lift' use 'go_to.py'."""
    if name.startswith("python") and cmdline:
        for part in cmdline.split()[1:]:
            if part.endswith(".py"):
                return Path(part).name
    return name


def summarise(rows):
    """Average CPU % and memory from logged rows (dicts with COLUMNS keys).

    Returns {"system_cpu_avg": float or None, "samples": int,
             "processes": {name: {"cpu_avg", "mem_avg_mb", "samples"}}}.
    Processes with the same label (e.g. several python nodes) are kept apart
    by pid while averaging, then added together per label per second, so the
    per-label average is "CPU used by that program" even if it restarts.
    """
    system = [float(r["cpu_percent"]) for r in rows if r["scope"] == "system"]

    per_tick = defaultdict(lambda: [0.0, 0.0])          # (label, tick) -> [cpu, mem]
    for r in rows:
        if r["scope"] != "process":
            continue
        key = (r["name"], r["elapsed_s"])
        per_tick[key][0] += float(r["cpu_percent"])
        per_tick[key][1] += float(r["mem_mb"])

    acc = defaultdict(lambda: [0.0, 0.0, 0])
    for (label, _), (cpu, mem) in per_tick.items():
        acc[label][0] += cpu
        acc[label][1] += mem
        acc[label][2] += 1

    processes = {
        label: {"cpu_avg": round(c / n, 1), "mem_avg_mb": round(m / n, 1), "samples": n}
        for label, (c, m, n) in acc.items()
    }
    return {
        "system_cpu_avg": round(sum(system) / len(system), 1) if system else None,
        "samples": len(system),
        "processes": processes,
    }


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def cpu_avg_from_csv(path):
    """The cpu_avg value for trials.csv: average whole-machine CPU %."""
    return summarise(read_rows(path))["system_cpu_avg"]


def format_summary(summary):
    lines = []
    if summary["system_cpu_avg"] is None:
        lines.append("No samples logged.")
        return "\n".join(lines)
    lines.append(f"Samples: {summary['samples']} s")
    lines.append(f"cpu_avg (whole machine): {summary['system_cpu_avg']} %")
    procs = sorted(summary["processes"].items(), key=lambda kv: -kv[1]["cpu_avg"])
    if procs:
        lines.append(f"{'process':<28}{'cpu % (per core)':>18}{'mem MB':>10}")
        for label, p in procs:
            lines.append(f"{label:<28}{p['cpu_avg']:>18}{p['mem_avg_mb']:>10}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live sampling (needs psutil)
# ---------------------------------------------------------------------------

def sample(psutil, start, patterns, watch_all, known):
    """One second's rows. `known` keeps psutil.Process objects between calls,
    because cpu_percent() measures since the previous call on the same object."""
    now = time.time()
    stamp = datetime.now().isoformat(timespec="seconds")
    elapsed = round(now - start, 1)
    rows = [{"timestamp": stamp, "elapsed_s": elapsed, "scope": "system", "pid": "",
             "name": "system", "cpu_percent": psutil.cpu_percent(interval=None),
             "mem_mb": round(psutil.virtual_memory().used / 1e6, 1)}]

    seen = set()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = proc.info["pid"]
            name = proc.info["name"] or ""
            cmdline = " ".join(proc.info["cmdline"] or [])
            if pid == psutil.Process().pid:
                continue                                   # don't log ourselves
            if not watch_all and not matches(name, cmdline, patterns):
                continue
            seen.add(pid)
            if pid not in known:
                known[pid] = (proc, short_name(name, cmdline))
                proc.cpu_percent(interval=None)            # first call is always 0
                continue
            p, label = known[pid]
            rows.append({"timestamp": stamp, "elapsed_s": elapsed, "scope": "process",
                         "pid": pid, "name": label,
                         "cpu_percent": p.cpu_percent(interval=None),
                         "mem_mb": round(p.memory_info().rss / 1e6, 1)})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    for pid in list(known):                                # forget processes that ended
        if pid not in seen:
            del known[pid]
    return rows


def run(args):
    try:
        import psutil
    except ImportError:
        sys.exit("psutil is missing: pip install psutil  (or apt install python3-psutil)")

    patterns = DEFAULT_PATTERNS + (args.pattern or [])
    out = None
    writer = None
    path = None
    if not args.dry_run:
        path = Path(args.output) if args.output else CPU_DIR / f"{args.trial_id}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        out = open(path, "w", newline="")
        writer = csv.DictWriter(out, fieldnames=COLUMNS)
        writer.writeheader()
        print(f"Logging to {path} every {args.interval} s. Ctrl+C to stop.")
    else:
        print("DRY-RUN: printing samples, no file written.")

    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))

    psutil.cpu_percent(interval=None)                      # prime the system counter
    known = {}
    all_rows = []
    start = time.time()
    next_tick = start + args.interval
    try:
        while not stop["now"]:
            time.sleep(max(0.0, next_tick - time.time()))
            next_tick += args.interval
            rows = sample(psutil, start, patterns, args.all, known)
            all_rows.extend(rows)
            if writer:
                writer.writerows(rows)
                out.flush()
            if args.dry_run or args.verbose:
                procs = sum(1 for r in rows if r["scope"] == "process")
                print(f"{rows[0]['elapsed_s']:>7} s  system {rows[0]['cpu_percent']:>5} %  "
                      f"({procs} watched processes)")
            if args.duration and time.time() - start >= args.duration:
                break
    finally:
        if out:
            out.close()

    print()
    print(format_summary(summarise(all_rows)))
    if path:
        print(f"Saved: {path}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Log CPU and memory per process once per second during a trial.")
    parser.add_argument("--trial-id", default=datetime.now().strftime("trial_%Y%m%d_%H%M%S"),
                        help="names the output file trials/cpu/<trial-id>.csv")
    parser.add_argument("--output", help="write to this CSV instead of trials/cpu/")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between samples")
    parser.add_argument("--duration", type=float, default=0,
                        help="stop after this many seconds (0 = until Ctrl+C)")
    parser.add_argument("--all", action="store_true",
                        help="log every process, not only ROS / our scripts")
    parser.add_argument("--pattern", action="append",
                        help="extra process name to watch (can repeat)")
    parser.add_argument("--summary", metavar="CSV",
                        help="only print the averages of an existing log, then exit")
    parser.add_argument("--verbose", action="store_true", help="print every sample")
    parser.add_argument("--dry-run", action="store_true",
                        help="print samples to the screen, write no file")
    args = parser.parse_args(argv)

    if args.summary:
        print(format_summary(summarise(read_rows(args.summary))))
        return 0
    if args.interval <= 0:
        parser.error("--interval must be > 0")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
