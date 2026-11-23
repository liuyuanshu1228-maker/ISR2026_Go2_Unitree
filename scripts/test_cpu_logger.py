"""Tests for cpu_logger.py. Run from the scripts/ folder:
    python3 -m unittest test_cpu_logger -v

Pure Python: the summary tests do not need psutil. The live test is skipped
if psutil is not installed.
"""

import csv
import tempfile
import unittest
from pathlib import Path

import cpu_logger
from cpu_logger import COLUMNS, cpu_avg_from_csv, matches, short_name, summarise


def row(t, scope, name, cpu, mem=100.0, pid=""):
    return {"timestamp": "2026-11-24T10:00:00", "elapsed_s": str(t), "scope": scope,
            "pid": str(pid), "name": name, "cpu_percent": str(cpu), "mem_mb": str(mem)}


class MatchTests(unittest.TestCase):
    def test_ros_process_is_watched(self):
        self.assertTrue(matches("async_slam_toolbox_node", "", cpu_logger.DEFAULT_PATTERNS))
        self.assertTrue(matches("python3", "python3 scripts/odom_publisher.py",
                                cpu_logger.DEFAULT_PATTERNS))

    def test_other_process_is_ignored(self):
        self.assertFalse(matches("chrome", "/usr/bin/chrome --type=renderer",
                                 cpu_logger.DEFAULT_PATTERNS))

    def test_short_name_for_python_script(self):
        self.assertEqual(short_name("python3", "python3 /ws/repo/scripts/go_to.py lift"), "go_to.py")
        self.assertEqual(short_name("controller_server", "controller_server --ros-args"),
                         "controller_server")


class SummaryTests(unittest.TestCase):
    def test_system_average(self):
        rows = [row(1, "system", "system", 20), row(2, "system", "system", 40)]
        self.assertEqual(summarise(rows)["system_cpu_avg"], 30.0)
        self.assertEqual(summarise(rows)["samples"], 2)

    def test_same_label_is_added_per_second(self):
        # two python nodes both called "where_am_i_node.py" in the same second
        rows = [row(1, "system", "system", 50),
                row(1, "process", "where_am_i_node.py", 10, pid=1),
                row(1, "process", "where_am_i_node.py", 30, pid=2),
                row(2, "system", "system", 50),
                row(2, "process", "where_am_i_node.py", 20, pid=1)]
        p = summarise(rows)["processes"]["where_am_i_node.py"]
        self.assertEqual(p["cpu_avg"], 30.0)      # (10+30 + 20) / 2 seconds
        self.assertEqual(p["samples"], 2)

    def test_empty_log(self):
        self.assertIsNone(summarise([])["system_cpu_avg"])

    def test_cpu_avg_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "E1-001.csv"
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS)
                w.writeheader()
                w.writerows([row(1, "system", "system", 10),
                             row(1, "process", "slam_toolbox", 80, pid=5),
                             row(2, "system", "system", 30)])
            self.assertEqual(cpu_avg_from_csv(path), 20.0)


@unittest.skipUnless(__import__("importlib").util.find_spec("psutil"), "psutil not installed")
class LiveTests(unittest.TestCase):
    def test_short_run_writes_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.csv"
            cpu_logger.main(["--output", str(path), "--duration", "2", "--interval", "0.5"])
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertGreaterEqual(sum(r["scope"] == "system" for r in rows), 3)
            self.assertEqual(list(rows[0].keys()), COLUMNS)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cpu_logger.CPU_DIR = Path(tmp) / "cpu"
            cpu_logger.main(["--dry-run", "--duration", "1", "--interval", "0.5"])
            self.assertFalse(cpu_logger.CPU_DIR.exists())


if __name__ == "__main__":
    unittest.main()
