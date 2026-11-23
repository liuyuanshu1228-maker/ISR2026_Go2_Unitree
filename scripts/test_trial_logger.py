"""Tests for trial_logger.py. Run from the scripts/ folder:
    python3 -m unittest test_trial_logger -v

The tests write to a temporary file, never to the real trials/trials.csv.
"""

import csv
import tempfile
import unittest
from pathlib import Path

from trial_logger import COLUMNS, log_trial


class TrialLoggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "trials.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def read_rows(self):
        with open(self.path, newline="") as f:
            return list(csv.DictReader(f))

    def test_writes_header_and_one_row(self):
        trial_id = log_trial("E1", "clear", start="lab", goal="lift", reached_goal=True,
                             gap_cm=12, time_s=42.5, path=self.path)
        self.assertEqual(trial_id, "E1-001")
        with open(self.path) as f:
            self.assertEqual(f.readline().strip(), ",".join(COLUMNS))
        rows = self.read_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reached_goal"], "yes")
        self.assertEqual(rows[0]["gap_cm"], "12")
        self.assertEqual(rows[0]["touched"], "")   # not filled in

    def test_ids_count_per_experiment(self):
        ids = [
            log_trial("E1", "clear", "lab", "lift", True, path=self.path),
            log_trial("E1", "clear", "lab", "lift", False, path=self.path),
            log_trial("E2", "box", "lab", "lift", True, path=self.path),
        ]
        self.assertEqual(ids, ["E1-001", "E1-002", "E2-001"])
        self.assertEqual(len(self.read_rows()), 3)   # header written only once

    def test_rejects_unknown_condition(self):
        with self.assertRaises(ValueError):
            log_trial("E2", "chair", "lab", "lift", True, path=self.path)
