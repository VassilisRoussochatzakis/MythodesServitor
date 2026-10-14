"""Tiered results must match the Tiered Test tables in Mythodes_Akmon/Skills.typ."""

import unittest

from rolls import (
    Difficulty, Support, Tier, build_opposed_result, build_tiered_result, flip_roll, perform_test, resolve_test,
    support_problem,
)

D = Difficulty
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
# The worked examples from "Supporting Skills": mechanic, main skill, main roll, supporting skills and their own
# rolls (none for mechanics that reuse the main roll, or that must not roll), final result, main difficulty.
SUPPORT_EXAMPLES = [
    ("Honing", 70, 71, [95], [], T.PARTIAL_FAILURE),
    ("Honing", 70, 55, [95], [], T.SUPERB_SUCCESS),
    ("Honing", 20, 11, [101], [], T.GRAND_SUCCESS),
    ("Bolstering", 70, 71, [95], [], T.STANDARD_SUCCESS),
    ("Bolstering", 60, 93, [90], [], T.PARTIAL_FAILURE),
    ("Bolstering", 20, 11, [101], [], T.GRAND_SUCCESS),
    ("Reining", 70, 71, [95], [70], T.STANDARD_SUCCESS),
    ("Reining", 80, 70, [100], [40], T.GRAND_SUCCESS),
    ("Reining", 80, 95, [90], [98], T.PARTIAL_FAILURE),
    ("Reining", 80, 95, [90], [17], T.STANDARD_SUCCESS),
    ("Empowering", 70, 71, [95], [], T.PARTIAL_FAILURE),
    ("Empowering", 80, 70, [100], [40], T.SUPERB_SUCCESS),
    ("Empowering", 80, 70, [100], [20], T.GRAND_SUCCESS),
    # Gambit's supporting 65 is Tested at Formidable (33). Standard eases Hard to Standard (90) and Partial
    # hardens it to Formidable (45); Superb also adds a Tier, and Critical eases it to Easy (135) and adds two.
    ("Gambit", 90, 80, [65], [26], T.STANDARD_SUCCESS, D.HARD),
    ("Gambit", 90, 50, [65], [37], T.PARTIAL_FAILURE, D.HARD),
    ("Gambit", 90, 80, [65], [15], T.SUPERB_SUCCESS, D.HARD),
    ("Gambit", 90, 80, [65], [3], T.CRITICAL_SUCCESS, D.HARD),
    ("Temper", 90, 85, [60], [21], T.SUPERB_SUCCESS),
    ("Temper", 90, 85, [60], [70], T.STANDARD_SUCCESS),
    ("Attune", 90, 85, [60], [], T.STANDARD_SUCCESS),
    ("Attune", 90, 45, [60], [], T.GRAND_SUCCESS),
    ("Ward", 90, 97, [60], [35], T.PARTIAL_FAILURE),
    ("Ward", 50, 99, [30], [2], T.STANDARD_SUCCESS),
    ("Ward", 50, 80, [30], [8], T.PARTIAL_FAILURE),
    ("Mend", 90, 97, [60], [35], T.FAILURE),
    ("Mend", 50, 78, [30], [25], T.PARTIAL_FAILURE),
    ("Mend", 50, 65, [30], [25], T.STANDARD_SUCCESS),
    ("Rally", 90, 97, [50, 75, 25], [30, 40, 20], T.PARTIAL_FAILURE),
    ("Mirror", 90, 91, [75], [40], T.GRAND_SUCCESS),
    # No worked examples in the rules for these.
    ("Foretelling", 60, 70, [90], [10], T.STANDARD_SUCCESS, D.HARD),  # Grand vs 60: Hard becomes Easy, 70 vs 90.
    ("Foretelling", 60, 1, [90], [100], T.FUMBLE),
    ("Usurping", 50, 60, [80], [], T.STANDARD_SUCCESS),
    ("Redeem", 50, 80, [40], [30], T.STANDARD_SUCCESS),
]


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

    def test_supporting_skill_examples(self):
        for kind, main, roll, ratings, rolls, tier, *difficulty in SUPPORT_EXAMPLES:
            support = Support(kind, ratings, ["Aid"] * len(ratings), rolls)
            _, results, text = perform_test("Ann", main, (difficulty or [D.STANDARD])[0], roll=roll, support=support)
            self.assertEqual(results["result"], tier, (kind, main, roll, rolls))
            self.assertTrue(text.endswith(f"**{tier.name.replace('_', ' ').title()}**!"), text)
            # Ward rolls its support before the main roll; Temper only after a successful one.
            if kind in ("Ward", "Temper"):
                self.assertEqual(text.index("*" + kind) < text.index("**Ann** rolled"), kind == "Ward", text)

    def test_support_granted_success_loses_ties(self):
        redeemed = Support("Redeem", [40], rolls=[30])
        result = build_opposed_result(50, your_roll=80, your_support=redeemed, opponent_skill_rating=50,
                                      opponent_roll=40, your_name="Ann", opponent_name="Bob")
        self.assertIn("**Bob** wins with a **marginal success**", result)

    def test_support_requirements(self):
        self.assertIsNone(support_problem(70, D.STANDARD, Support("Honing", [95])))
        self.assertIn("higher than", support_problem(70, D.STANDARD, Support("Honing", [60])))
        self.assertIn("equal to or lower", support_problem(70, D.HARD, Support("Rally", [50, 80])))
        self.assertIn("harder than Standard", support_problem(90, D.STANDARD, Support("Gambit", [65])))
        self.assertIn("die roll", support_problem(90, D.AUTOMATIC, Support("Mend", [60])))


if __name__ == "__main__":
    unittest.main()
