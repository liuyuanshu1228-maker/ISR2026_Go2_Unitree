"""Run beside places.py with: python3 test_where_am_i.py"""

import unittest

from places import where_am_i

class NamedPlaceTests(unittest.TestCase):
    def test_sample_map(self):
        # Lab (0, 0), lift (5, 0), both with a 1 m inclusive radius.
        cases = [
            ((0.2, 0), 'lab'),
            ((4.5, 0), 'lift'),
            ((2.5, 0), 'unknown'),
            ((0, 1), 'lab'),
            ((0, 1.01), 'unknown'),
            ((0.8, 0.8), 'unknown'),
        ]
        for point, expected in cases:
            with self.subTest(point=point, expected=expected):
                self.assertEqual(where_am_i(*point), expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
