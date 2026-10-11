"""Shared roll rules and result formatting for slash commands and guided setup."""

from enum import Enum
from fractions import Fraction
import math
import random
from typing import Optional


class Difficulty(Enum):
    IMPOSSIBLE = 0.0
    HERCULEAN = 0.1
    FORMIDABLE = 0.5
    HARD = 2 / 3
    STANDARD = 1.0
    EASY = 1.5
    VERY_EASY = 2.0
    TRIVIAL = 3.0
    AUTOMATIC = 100.0


class Tier(Enum):
    FUMBLE = 0
    SERIOUS_FAILURE = 1
    FAILURE = 2
    PARTIAL_FAILURE = 3
    STANDARD_SUCCESS = 4
    SUPERB_SUCCESS = 5
    GRAND_SUCCESS = 6
    CRITICAL_SUCCESS = 7


def modify_skill_rating(skill_rating: int, difficulty: Difficulty, modifier: int = 0) -> int:
    skill_rating += modifier
    if difficulty in (Difficulty.AUTOMATIC, Difficulty.IMPOSSIBLE):
        return skill_rating

    # Use exact fractions so rounding up cannot change an integer boundary.
    multiplier = Fraction(2, 3) if difficulty == Difficulty.HARD else Fraction(str(difficulty.value))
    return math.ceil(skill_rating * multiplier)


def resolve_test(
    skill_rating: int,
    roll: Optional[int] = None,
    tiered: bool = False,
    difficulty: Difficulty = Difficulty.STANDARD,
) -> dict:
    """Resolve an already-modified skill rating, or a difficulty requiring no roll."""
    if difficulty == Difficulty.AUTOMATIC:
        # Automatic Tiered Tests count as the best possible Grand Success.
        return {"roll": None, "result": Tier.GRAND_SUCCESS if tiered else Tier.STANDARD_SUCCESS, "success": True}
    if difficulty == Difficulty.IMPOSSIBLE:
        return {"roll": None, "result": Tier.SERIOUS_FAILURE, "success": False}

    if roll is None:
        roll = random.randint(1, 100)

    # Fixed values
    if roll == 100:
        return {"roll": roll, "result": Tier.FUMBLE, "success": False}

    if roll == 99:
        if skill_rating < 100:
            return {"roll": roll, "result": Tier.FUMBLE, "success": False}
        else:
            return {"roll": roll, "result": Tier.SERIOUS_FAILURE, "success": False}

    if 96 <= roll <= 98:
        return {"roll": roll, "result": Tier.SERIOUS_FAILURE, "success": False}

    # Calculate Tier Thresholds
    # 01 is always a Critical Success and 02-05 are always at least a Standard Success.
    crit_thresh = max(math.ceil(Fraction(skill_rating, 10)), 1)
    grand_thresh = math.ceil(Fraction(skill_rating * 3, 10))
    superb_thresh = math.ceil(Fraction(skill_rating * 3, 5))
    standard_thresh = max(skill_rating, 5)
    partial_failure_thresh = math.ceil(Fraction(skill_rating * 3, 2))
    failure_thresh = skill_rating * 2

    # Determine Result
    result_tier = Tier.FAILURE
    is_success = False

    if tiered == False:
        if roll <= crit_thresh:
            result_tier = Tier.CRITICAL_SUCCESS
            is_success = True
        elif roll <= standard_thresh:
            result_tier = Tier.STANDARD_SUCCESS
            is_success = True
        else:
            result_tier = Tier.FAILURE
            is_success = False
    else:
        if roll <= crit_thresh:
            result_tier = Tier.CRITICAL_SUCCESS
            is_success = True
        elif roll <= grand_thresh:
            result_tier = Tier.GRAND_SUCCESS
            is_success = True
        elif roll <= superb_thresh:
            result_tier = Tier.SUPERB_SUCCESS
            is_success = True
        elif roll <= standard_thresh:
            result_tier = Tier.STANDARD_SUCCESS
            is_success = True
        elif roll <= partial_failure_thresh:
            result_tier = Tier.PARTIAL_FAILURE
            is_success = False
        elif roll <= failure_thresh:
            result_tier = Tier.FAILURE
            is_success = False
        else:
            result_tier = Tier.SERIOUS_FAILURE
            is_success = False

    return {"roll": roll, "result": result_tier, "success": is_success}


def format_test_result(
    subject: str, skill_rating: int, results: dict, skill_name: Optional[str] = None,
    *, original_skill_rating: Optional[int] = None,
    difficulty: Difficulty = Difficulty.STANDARD, modifier: int = 0,
) -> str:
    result_name = results['result'].name.replace("_", " ").title()
    skill_suffix = f" on **{skill_name}**" if skill_name else ""
    details = []
    if difficulty != Difficulty.STANDARD:
        if original_skill_rating is not None:
            details.append(f"original: **{original_skill_rating}**")
        if modifier:
            details.append(f"modifier: **{modifier:+d}**")
        difficulty_name = difficulty.name.replace("_", " ").title()
        details.append(f"difficulty: **{difficulty_name}**")
    difficulty_suffix = f" ({', '.join(details)})" if details else ""
    if results['roll'] is None:
        action = "succeeds automatically" if results['success'] else "cannot attempt an impossible test"
        return f"\n**{subject}** {action}{difficulty_suffix}.\n**{result_name}**{skill_suffix}!"
    return f"\n**{subject}** rolled: **{results['roll']}** with a target of **{skill_rating}**{difficulty_suffix}\n**{result_name}**{skill_suffix}!"


def get_victory_magnitude(levels_of_success: int) -> str:
    """Name the magnitude of a victory from its nonnegative tier difference."""
    if levels_of_success >= 6:
        return "Absolute"
    if levels_of_success >= 4:
        return "Overwhelming"
    if levels_of_success >= 2:
        return "Decisive"
    if levels_of_success == 1:
        return "Clear"
    return "Marginal"


def build_tiered_result(
    skill_rating: int,
    difficulty: Difficulty = Difficulty.STANDARD,
    modifier: int = 0,
    roll: Optional[int] = None,
    your_name: str = "You",
    comment: Optional[str] = None,
    skill_name: Optional[str] = None,
) -> str:
    """Resolve a single test and return its public result message."""
    original_skill_rating = skill_rating
    skill_rating = modify_skill_rating(skill_rating, difficulty, modifier)
    results = resolve_test(skill_rating, roll, True, difficulty)

    results_str = format_test_result(
        your_name, skill_rating, results, skill_name,
        original_skill_rating=original_skill_rating, difficulty=difficulty, modifier=modifier,
    )
    if comment:
        results_str = f"**Test:** {comment}\n{results_str}"

    return results_str


def build_opposed_result(
    your_skill_rating: int,
    your_difficulty: Difficulty = Difficulty.STANDARD,
    your_modifier: int = 0,
    your_roll: Optional[int] = None,
    opponent_skill_rating: Optional[int] = None,
    opponent_difficulty: Difficulty = Difficulty.STANDARD,
    opponent_modifier: int = 0,
    opponent_roll: Optional[int] = None,
    your_name: str = "You",
    opponent_name: str = "Your opponent",
    comment: Optional[str] = None,
    your_skill_name: Optional[str] = None,
    opponent_skill_name: Optional[str] = None,
) -> str:
    """Resolve opposed tests, retaining support for a single participant."""
    your_victory = f"**{your_name}** wins" + (f" **{your_skill_name}**" if your_skill_name else "")
    opponent_victory = f"**{opponent_name}** wins" + (f" **{opponent_skill_name}**" if opponent_skill_name else "")

    # If opposed, make opponent's roll
    if opponent_skill_rating is not None:
        original_opponent_skill_rating = opponent_skill_rating
        opponent_skill_rating = modify_skill_rating(opponent_skill_rating, opponent_difficulty, opponent_modifier)
        opponent_results = resolve_test(opponent_skill_rating, opponent_roll, True, opponent_difficulty)
        opponent_results_str = format_test_result(
            opponent_name, opponent_skill_rating, opponent_results, opponent_skill_name,
            original_skill_rating=original_opponent_skill_rating,
            difficulty=opponent_difficulty, modifier=opponent_modifier,
        )
    else:
        opponent_results_str = ""

    original_your_skill_rating = your_skill_rating
    your_skill_rating = modify_skill_rating(your_skill_rating, your_difficulty, your_modifier)
    your_results = resolve_test(your_skill_rating, your_roll, True, your_difficulty)

    if opponent_skill_rating is not None:
        differential = your_results["result"].value - opponent_results["result"].value
        has_winner = True
        if your_results["success"] == False and opponent_results["success"] == False:
            has_winner = False
            winner_str = f'**{your_name}** and **{opponent_name}** both fail.'
        elif differential > 0:
            level_label = "Level" if differential == 1 else "Levels"
            winner_str = f'{your_victory} with **{differential} {level_label} of Success**!'
        elif differential < 0:
            level_label = "Level" if differential == -1 else "Levels"
            winner_str = f'{opponent_victory} with **{abs(differential)} {level_label} of Success**!'
        else:
            # When a result needs no roll, break a tied tier using skill ratings.
            both_rolled = your_results["roll"] is not None and opponent_results["roll"] is not None
            if both_rolled and your_results["roll"] > opponent_results["roll"]:
                winner_str = f'{your_victory} with a **marginal success**.'
            elif both_rolled and your_results["roll"] < opponent_results["roll"]:
                winner_str = f'{opponent_victory} with a **marginal success**.'
            elif your_skill_rating > opponent_skill_rating:
                winner_str = f'{your_victory} with a **marginal success**.'
            elif your_skill_rating < opponent_skill_rating:
                winner_str = f'{opponent_victory} with a **marginal success**.'
            else:
                has_winner = False
                winner_str = f'A true tie!!!'
        if has_winner:
            magnitude = get_victory_magnitude(abs(differential))
            winner_str += f'\nMagnitude of victory: **{magnitude}**.'
    else:
        winner_str = ''

    your_results_str = format_test_result(
        your_name, your_skill_rating, your_results, your_skill_name,
        original_skill_rating=original_your_skill_rating,
        difficulty=your_difficulty, modifier=your_modifier,
    )

    final_output = your_results_str + "\n" + opponent_results_str + "\n\n" + winner_str
    if comment:
        final_output = f"**Test:** {comment}\n{final_output}"

    return final_output
