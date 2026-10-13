"""Tiered results must match the Tiered Test tables in Mythodes_Akmon/Skills.typ."""

import unittest

from rolls import Difficulty, Tier, build_tiered_result, flip_roll, resolve_test

T = Tier
TABLES = {
    40: [(1, 4, T.CRITICAL_SUCCESS), (5, 12, T.GRAND_SUCCESS), (13, 24, T.SUPERB_SUCCESS),
         (25, 40, T.STANDARD_SUCCESS), (41, 60, T.PARTIAL_FAILURE), (61, 80, T.FAILURE),
         (81, 98, T.SERIOUS_FAILURE), (99, 100, T.FUMBLE)],
    60: [(1, 6, T.CRITICAL_SUCCESS), (7, 18, T.GRAND_SUCCESS), (19, 36, T.SUPERB_SUCCESS),
         (37, 60, T.STANDARD_SUCCESS), (61, 90, T.PARTIAL_FAILURE), (91, 95, T.FAILURE),
         (96, 98, T.SERIOUS_FAILURE), (99, 100, T.FUMBLE)],
    100: [(1, 10, T.CRITICAL_SUCCESS), (11, 30, T.GRAND_SUCCESS), (31, 60, T.SUPERB_SUCCESS),
          (61, 95, T.STANDARD_SUCCESS), (96, 99, T.SERIOUS_FAILURE), (100, 100, T.FUMBLE)],
}


class TieredTests(unittest.TestCase):
    def test_rulebook_tables(self):
        for skill, rows in TABLES.items():
            for lo, hi, tier in rows:
                for roll in range(lo, hi + 1):
                    self.assertEqual(resolve_test(skill, roll, True)["result"], tier, (skill, roll))

    def test_low_rolls_always_succeed(self):
        self.assertEqual(resolve_test(0, 1, True)["result"], T.CRITICAL_SUCCESS)
        for roll in range(2, 6):
            self.assertTrue(resolve_test(1, roll, True)["success"], roll)

    def test_tiered_command_uses_tiers(self):
        self.assertIn("Superb Success", build_tiered_result(40, roll=20))
        self.assertIn("Grand Success", build_tiered_result(40, difficulty=Difficulty.AUTOMATIC))

    def test_flip_swaps_d100_dice(self):
        for roll, flipped in ((71, 17), (7, 70), (10, 1), (100, 100), (55, 55)):
            self.assertEqual(flip_roll(roll), flipped, roll)
        self.assertEqual(sorted(flip_roll(roll) for roll in range(1, 101)), list(range(1, 101)))


if __name__ == "__main__":
    unittest.main()
