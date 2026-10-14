"""Shared roll rules and result formatting for slash commands and guided setup."""

from dataclasses import dataclass, field
from enum import Enum, IntEnum
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


class Tier(IntEnum):
    FUMBLE = 0
    SERIOUS_FAILURE = 1
    FAILURE = 2
    PARTIAL_FAILURE = 3
    STANDARD_SUCCESS = 4
    SUPERB_SUCCESS = 5
    GRAND_SUCCESS = 6
    CRITICAL_SUCCESS = 7


# Supporting Skill mechanics in rulebook order, summarised for the setup form.
SUPPORTS = {
    "Honing": "Higher skill. Same roll; a successful test gains +1 Tier if the support's Tier is better.",
    "Bolstering": "Higher skill. Same roll; +1 Tier if the support's Tier is better, even on a failure.",
    "Empowering": "Higher skill. Rolled after a successful test; the better Tier counts.",
    "Reining": "Higher skill. Rolled first; a success guarantees at least a Standard Success.",
    "Foretelling": "Higher skill. Rolled first; its Tier makes your test easier or harder.",
    "Usurping": "Higher skill. Same roll against both skills; the better result counts.",
    "Gambit": "Equal or lower skill, penalized test. Rolled first, a step harder; shifts difficulty, may add Tiers.",
    "Temper": "Equal or lower skill. Rolled after a successful test; a success adds +1 Tier.",
    "Attune": "Equal or lower skill. Same roll; +1 Tier if it succeeds against both skills.",
    "Ward": "Equal or lower skill. Rolled first; a success softens your failures.",
    "Mend": "Equal or lower skill. Rolled after a failed test, one penalty less; a success adds +1 Tier.",
    "Rally": "Up to 3 equal or lower skills, rolled after a failed test; each success adds +1 Tier.",
    "Redeem": "Equal or lower skill. Rolled after a failed test; a success makes it a Standard Success.",
    "Mirror": "Equal or lower skill. Rolled first; a success lets your roll be flipped.",
}
# These need Supporting Skills higher than the Main Skill; the rest need them equal or lower.
HIGHER_SUPPORTS = {"Honing", "Bolstering", "Empowering", "Reining", "Foretelling", "Usurping"}
# A Supporting Tier's (penalties negated, steps easier, Tiers added to the roll) for the Main Test;
# a Fumble is an automatic Fumble.
FORETELLING = {
    Tier.SERIOUS_FAILURE: (0, -3, 0), Tier.FAILURE: (0, -2, 0), Tier.PARTIAL_FAILURE: (0, -1, 0),
    Tier.STANDARD_SUCCESS: (1, 0, 0), Tier.SUPERB_SUCCESS: (2, 0, 0), Tier.GRAND_SUCCESS: (2, 1, 0),
    Tier.CRITICAL_SUCCESS: (2, 2, 0),
}
GAMBIT = {
    **FORETELLING, Tier.STANDARD_SUCCESS: (0, 1, 0), Tier.SUPERB_SUCCESS: (0, 1, 1),
    Tier.GRAND_SUCCESS: (0, 2, 1), Tier.CRITICAL_SUCCESS: (0, 2, 2),
}
NO_ROLL = (Difficulty.AUTOMATIC, Difficulty.IMPOSSIBLE)


@dataclass
class Support:
    """Supporting Skill ratings (several only for Rally), each Tested in order with its own d100."""
    kind: str
    ratings: list[int]
    names: list[str] = field(default_factory=list)
    rolls: list[int] = field(default_factory=list)


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


def flip_roll(roll: int) -> int:
    """Swap a d100's tens and units dice: 71 becomes 17, 07 becomes 70, and 00 (100) stays 100."""
    return roll % 10 * 10 + roll // 10 % 10 or 100


def title(member: Enum) -> str:
    return member.name.replace("_", " ").title()


def shift(difficulty: Difficulty, *, easier: int = 0, negate: int = 0) -> Difficulty:
    """Move a difficulty by steps; negating penalties stops at Standard, and four steps reach Automatic or Impossible."""
    steps = list(Difficulty)
    index = steps.index(difficulty)
    index = max(index, min(index + negate, steps.index(Difficulty.STANDARD)))
    return steps[min(max(index + easier, 0), len(steps) - 1)]


def improve(tier: Tier, tiers: int = 1) -> Tier:
    return Tier(min(tier + tiers, Tier.CRITICAL_SUCCESS))


def describe_roll(
    subject: str, skill_rating: int, results: dict, *, original_skill_rating: Optional[int] = None,
    difficulty: Difficulty = Difficulty.STANDARD, modifier: int = 0,
) -> str:
    details = []
    if difficulty != Difficulty.STANDARD:
        if original_skill_rating is not None:
            details.append(f"original: **{original_skill_rating}**")
        if modifier:
            details.append(f"modifier: **{modifier:+d}**")
        details.append(f"difficulty: **{title(difficulty)}**")
    difficulty_suffix = f" ({', '.join(details)})" if details else ""
    if results['roll'] is None:
        action = "succeeds automatically" if results['success'] else "cannot attempt an impossible test"
        return f"**{subject}** {action}{difficulty_suffix}"
    return f"**{subject}** rolled: **{results['roll']}** with a target of **{skill_rating}**{difficulty_suffix}"


def describe_tier(tier: Tier, skill_name: Optional[str] = None) -> str:
    skill_suffix = f" on **{skill_name}**" if skill_name else ""
    return f"**{title(tier)}**{skill_suffix}!"


def perform_test(
    name: str, skill_rating: int, difficulty: Difficulty = Difficulty.STANDARD, modifier: int = 0,
    roll: Optional[int] = None, skill_name: Optional[str] = None, support: Optional[Support] = None,
) -> tuple[int, dict, str]:
    """Resolve a Tiered Test and any Supporting Skills, describing each roll in the order it happens.

    Returns the final target, the final results and their description.
    """
    target = modify_skill_rating(skill_rating, difficulty, modifier)
    if support is None or difficulty in NO_ROLL:
        results = resolve_test(target, roll, True, difficulty)
        roll_line = describe_roll(
            name, target, results, original_skill_rating=skill_rating, difficulty=difficulty, modifier=modifier,
        )
        period = "." if results['roll'] is None else ""
        return target, results, f"\n{roll_line}{period}\n{describe_tier(results['result'], skill_name)}"

    kind, lines = support.kind, []
    roll = random.randint(1, 100) if roll is None else roll

    def supporting(i: int, support_difficulty: Difficulty = difficulty, same_roll: bool = False) -> Tier:
        """Test one Supporting Skill, describe it, and return its Tier."""
        support_target = modify_skill_rating(support.ratings[i], support_difficulty)
        results = resolve_test(support_target, roll if same_roll else support.rolls[i], True, support_difficulty)
        rolled = "the same roll" if same_roll else f"rolled **{results['roll']}**"
        action = "cannot be attempted" if results['roll'] is None else f"{rolled} with a target of **{support_target}**"
        skill = f" with **{support.names[i]}**" if i < len(support.names) and support.names[i] else ""
        hardness = "" if support_difficulty == Difficulty.STANDARD else f" ({title(support_difficulty)})"
        lines.append(f"*{kind}*{skill}{hardness}: {action} → {title(results['result'])}")
        return results['result']

    diff, first, bonus = difficulty, None, 0
    if kind in ("Reining", "Foretelling", "Gambit", "Ward", "Mirror"):
        # These Test the Supporting Skill before the Main Skill.
        first = supporting(0, shift(difficulty, easier=-1) if kind == "Gambit" else difficulty)
        if kind in ("Foretelling", "Gambit") and first != Tier.FUMBLE:
            negate, easier, bonus = (FORETELLING if kind == "Foretelling" else GAMBIT)[first]
            diff = shift(difficulty, easier=easier, negate=negate)
            lines[-1] += f"; the test {'stays' if diff == difficulty else 'becomes'} {title(diff)}"
            if bonus:
                lines[-1] += f", +{bonus} Tier to the roll"

    target = modify_skill_rating(skill_rating, diff, modifier)
    if kind in ("Foretelling", "Gambit") and first == Tier.FUMBLE:
        results = {"roll": None, "result": Tier.FUMBLE, "success": False}
        lines.append(f"**{name}** fumbles automatically")
    else:
        results = resolve_test(target, roll, True, diff)
        roll_line = describe_roll(
            name, target, results, original_skill_rating=skill_rating, difficulty=diff, modifier=modifier,
        )
        lines.append(f"{roll_line} → {title(results['result'])}")

    S = Tier.STANDARD_SUCCESS
    main = final = results['result']
    if kind == "Gambit":
        final = improve(main, bonus)
    elif kind == "Reining" and main != Tier.FUMBLE:
        if first >= S:
            final = improve(max(first, main)) if main >= S else S
        elif main < S:
            final = max(first, main)
    elif kind == "Ward" and first >= S and main < S:
        if first == Tier.CRITICAL_SUCCESS:
            final = S
        elif main != Tier.FUMBLE:
            # Each Level of Success softens the failure, but at best to a Partial Failure.
            final = Tier(min(main + first - Tier.PARTIAL_FAILURE, Tier.PARTIAL_FAILURE))
    elif kind == "Mirror" and first >= S:
        flipped = resolve_test(target, flip_roll(roll), True, diff)
        # A higher roll in the same Tier wins opposed ties, so it is also worth flipping for.
        if (flipped['result'], flipped['roll']) > (main, roll):
            lines.append(f"*Mirror*: flipped to **{flipped['roll']}** → {title(flipped['result'])}")
            results, final = flipped, flipped['result']
    elif kind in ("Honing", "Empowering", "Temper") and main < S or kind in ("Mend", "Redeem", "Rally") and main >= S:
        lines.append(f"*{kind}*: not used")
    elif kind == "Usurping":
        final = max(main, supporting(0, same_roll=True))
    elif kind in ("Honing", "Bolstering"):
        if supporting(0, same_roll=True) > main:
            final = improve(main)
    elif kind == "Attune":
        if supporting(0, same_roll=True) >= S and main >= S:
            final = improve(main)
    elif kind == "Empowering":
        final = max(main, supporting(0))
    elif kind == "Temper":
        if supporting(0) >= S:
            final = improve(main)
    elif kind == "Mend":
        if supporting(0, shift(difficulty, negate=1)) >= S and main != Tier.FUMBLE:
            final = improve(main)
    elif kind == "Redeem":
        if supporting(0) >= S:
            final = S
    elif kind == "Rally":
        # Each success, at a stacking one-step penalty, softens the failure; any failure ends the Rally.
        for i in range(len(support.ratings)):
            if final >= S or supporting(i, shift(difficulty, easier=-i)) < S:
                break
            final = Tier(final + 1)

    # A success granted to a failed roll has no D100 result to win ties with.
    tie_roll = 0 if final >= S and results['result'] < S and kind != "Usurping" else results['roll']
    lines.append(describe_tier(final, skill_name))
    return target, {"roll": tie_roll, "result": final, "success": final >= S}, "\n" + "\n".join(lines)


def support_problem(skill_rating: int, difficulty: Difficulty, support: Support) -> Optional[str]:
    """Explain why Supporting Skills cannot help this Main Skill Test, or return None if they can."""
    kind = support.kind
    if difficulty in NO_ROLL:
        return f"{kind} needs a test with a die roll, not an {title(difficulty)} one."
    higher = kind in HIGHER_SUPPORTS
    if any((rating > skill_rating) != higher for rating in support.ratings):
        relation = "higher than" if higher else "equal to or lower than"
        return f"{kind} needs supporting skill ratings {relation} the main skill rating ({skill_rating})."
    if kind == "Gambit" and difficulty.value >= Difficulty.STANDARD.value:
        return "Gambit needs a test that is already harder than Standard."
    return None


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
    support: Optional[Support] = None,
) -> str:
    """Resolve a single test and return its public result message."""
    results_str = perform_test(your_name, skill_rating, difficulty, modifier, roll, skill_name, support)[2]
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
    your_support: Optional[Support] = None,
    opponent_support: Optional[Support] = None,
) -> str:
    """Resolve opposed tests, also allowing a single participant."""
    your_victory = f"**{your_name}** wins" + (f" **{your_skill_name}**" if your_skill_name else "")
    opponent_victory = f"**{opponent_name}** wins" + (f" **{opponent_skill_name}**" if opponent_skill_name else "")

    # If opposed, make opponent's roll
    if opponent_skill_rating is not None:
        opponent_skill_rating, opponent_results, opponent_results_str = perform_test(
            opponent_name, opponent_skill_rating, opponent_difficulty, opponent_modifier,
            opponent_roll, opponent_skill_name, opponent_support,
        )
    else:
        opponent_results_str = ""

    your_skill_rating, your_results, your_results_str = perform_test(
        your_name, your_skill_rating, your_difficulty, your_modifier, your_roll, your_skill_name, your_support,
    )

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

    final_output = your_results_str + "\n" + opponent_results_str + "\n\n" + winner_str
    if comment:
        final_output = f"**Test:** {comment}\n{final_output}"

    return final_output
