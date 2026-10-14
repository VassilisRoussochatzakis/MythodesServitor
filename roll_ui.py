"""Private, guided Discord forms for preparing a roll, and buttons for changing a posted roll."""

from dataclasses import dataclass, replace
from functools import partial
import logging
import random
from typing import Optional

import discord

from rolls import (
    SUPPORTS, Difficulty, Support, build_opposed_result, build_tiered_result, flip_roll, modify_skill_rating,
    support_problem,
)


log = logging.getLogger(__name__)
SETUP_TIMEOUT = 600


def log_expired_interaction(interaction: discord.Interaction, error: Exception) -> bool:
    if not isinstance(error, discord.NotFound) or error.code != 10062:
        return False
    age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
    log.warning(
        "Discord rejected interaction %s (10062; age %.2fs, gateway latency %.0fms). "
        "It may have expired or already been handled. If the form opened, check for "
        "another bot instance; otherwise retry the command or button.",
        interaction.id, age, interaction.client.latency * 1000,
    )
    # A rejected initial response cannot be repaired by replying to the same token.
    return True


@dataclass
class Participant:
    name: str
    skill_rating: Optional[int] = None
    difficulty: Difficulty = Difficulty.STANDARD
    modifier: int = 0
    roll: Optional[int] = None
    skill_name: str = ""
    support: Optional[Support] = None


def parse_integer(value: str, label: str, *, default: Optional[int] = None) -> Optional[int]:
    value = value.strip()
    if not value:
        return default
    try:
        # Avoid accepting Python-specific spellings such as 1_000.
        if not value.lstrip("+-").isdecimal():
            raise ValueError
        number = int(value)
    except ValueError:
        raise ValueError(f"{label} must be a whole number, such as 65 or -10.") from None
    if abs(number) > 2**53 - 1:
        raise ValueError(f"{label} is too large. Please enter a smaller whole number.")
    return number


def parse_roll(value: str, label: str) -> Optional[int]:
    number = parse_integer(value, label)
    if number is not None and not 1 <= number <= 100:
        raise ValueError(f"{label} must be between 1 and 100, or blank for a random roll.")
    return number


def parse_support(kind: str, ratings: str, names: str) -> Support:
    values = [parse_integer(value, "Supporting skill rating") for value in ratings.split(",")]
    if None in values:
        raise ValueError("Enter the supporting skill rating, such as 75.")
    if len(values) > (3 if kind == "Rally" else 1):
        raise ValueError("Rally takes up to three supporting skills." if kind == "Rally" else
                         f"{kind} takes one supporting skill; only Rally takes several.")
    return Support(kind, values, [name.strip() for name in names.split(",")] if kind == "Rally" else [names])


class SetupModal(discord.ui.Modal):
    def __init__(self, setup: "RollSetupView", title: str):
        super().__init__(title=title, timeout=SETUP_TIMEOUT)
        self.setup = setup

    def field(self, label: str, component, description: Optional[str] = None):
        self.add_item(discord.ui.Label(text=label, description=description, component=component))
        return component

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.setup.interaction_check(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await self.setup.on_error(interaction, error, None)


class ParticipantModal(SetupModal):
    def __init__(self, setup: "RollSetupView", opponent: bool = False):
        super().__init__(setup, "Opponent details" if opponent else "Your test details")
        self.opponent = opponent
        participant = setup.opponent if opponent else setup.your
        self.draft_key = "opponent" if opponent else "your"
        draft = setup.drafts.get(self.draft_key, {})
        self.name_input = self.field(
            "Character name",
            discord.ui.TextInput(
                default=draft.get("name", participant.name), required=False, max_length=100,
                placeholder="Leave blank to use the default name",
            ),
        )
        self.skill_input = self.field(
            "Skill rating",
            discord.ui.TextInput(
                default=draft.get("skill", "" if participant.skill_rating is None else str(participant.skill_rating)),
                required=not opponent, max_length=18, placeholder="e.g. 65",
            ),
            "Leave blank to roll only your side." if opponent else "Your skill before difficulty or modifiers.",
        )
        self.skill_name_input = self.field(
            "Skill name (optional)",
            discord.ui.TextInput(
                default=draft.get("skill_name", participant.skill_name), required=False,
                max_length=100, placeholder="e.g. Perception or Sword",
            ),
        )
        selected = draft.get("difficulty", participant.difficulty.name)
        self.difficulty_input = self.field(
            "Difficulty",
            discord.ui.Select(options=[
                discord.SelectOption(
                    label=difficulty.name.replace("_", " ").title(),
                    value=difficulty.name, default=difficulty.name == selected,
                )
                for difficulty in Difficulty
            ]),
            "Choose Standard unless the GM specifies another difficulty.",
        )
        self.modifier_input = self.field(
            "Modifier (optional)",
            discord.ui.TextInput(
                default=draft.get("modifier", str(participant.modifier)), required=False,
                max_length=18, placeholder="e.g. +10 or -20; blank means 0",
            ),
            "Added to your skill before difficulty is applied.",
        )

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.setup.interaction_check(interaction):
            return
        participant = self.setup.opponent if self.opponent else self.setup.your
        selected = self.difficulty_input.values
        difficulty = selected[0] if selected else next(
            option.value for option in self.difficulty_input.options if option.default
        )
        draft = {
            "name": self.name_input.value.strip(),
            "skill": self.skill_input.value.strip(),
            "skill_name": self.skill_name_input.value.strip(),
            "difficulty": difficulty,
            "modifier": self.modifier_input.value.strip(),
        }
        self.setup.drafts[self.draft_key] = draft
        try:
            skill = parse_integer(draft["skill"], "Skill rating")
            if skill is None and not self.opponent:
                raise ValueError("Enter your skill rating, such as 65.")
            modifier = parse_integer(draft["modifier"], "Modifier", default=0)
        except ValueError as error:
            button = "Opponent details" if self.opponent else "Your details"
            await self.setup.show_panel(
                interaction, error=f"{error} Click **{button}** to correct it; your entries are saved."
            )
            return

        participant.name = draft["name"] or self.setup.default_names[self.draft_key]
        participant.skill_rating = skill
        participant.skill_name = draft["skill_name"]
        participant.difficulty = Difficulty[difficulty]
        participant.modifier = modifier
        del self.setup.drafts[self.draft_key]
        await self.setup.show_panel(interaction)


class AdvancedModal(SetupModal):
    def __init__(self, setup: "RollSetupView"):
        super().__init__(setup, "Advanced options")
        draft = setup.drafts.get("advanced", {})
        self.comment_input = self.field(
            "What is this test for? (optional)",
            discord.ui.TextInput(
                default=draft.get("comment", setup.comment), required=False,
                max_length=1000, style=discord.TextStyle.paragraph,
                placeholder="e.g. Sneaking past the guards",
            ),
        )
        self.your_roll_input = self.field(
            "Your manual roll (optional)",
            discord.ui.TextInput(
                default=draft.get("your_roll", "" if setup.your.roll is None else str(setup.your.roll)),
                required=False, max_length=18, placeholder="1 to 100; blank means roll randomly",
            ),
            "Use this only to enter an already-rolled result.",
        )
        self.opponent_roll_input = None
        if setup.opponent is not None:
            self.opponent_roll_input = self.field(
                "Opponent's manual roll (optional)",
                discord.ui.TextInput(
                    default=draft.get("opponent_roll", "" if setup.opponent.roll is None else str(setup.opponent.roll)),
                    required=False, max_length=18, placeholder="1 to 100; blank means roll randomly",
                ),
            )

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.setup.interaction_check(interaction):
            return
        draft = {
            "comment": self.comment_input.value.strip(),
            "your_roll": self.your_roll_input.value.strip(),
            "opponent_roll": self.opponent_roll_input.value.strip() if self.opponent_roll_input else "",
        }
        self.setup.drafts["advanced"] = draft
        try:
            your_roll = parse_roll(draft["your_roll"], "Your manual roll")
            opponent_roll = parse_roll(draft["opponent_roll"], "Opponent's manual roll")
        except ValueError as error:
            await self.setup.show_panel(
                interaction, error=f"{error} Click **Advanced options** to correct it; your entries are saved."
            )
            return
        self.setup.comment = draft["comment"]
        self.setup.your.roll = your_roll
        if self.setup.opponent is not None:
            self.setup.opponent.roll = opponent_roll
        del self.setup.drafts["advanced"]
        await self.setup.show_panel(interaction)


class SupportModal(SetupModal):
    def __init__(self, setup: "RollSetupView", opponent: bool = False):
        super().__init__(setup, "Opponent support" if opponent else "Your support")
        self.opponent = opponent
        self.draft_key = "opponent_support" if opponent else "your_support"
        support = (setup.opponent if opponent else setup.your).support
        draft = setup.drafts.get(self.draft_key, {})
        selected = draft.get("kind", support.kind if support else "None")
        self.kind_input = self.field(
            "Support",
            discord.ui.Select(options=[
                discord.SelectOption(label="No support", value="None", default=selected == "None"),
                *(discord.SelectOption(label=kind, description=summary, default=kind == selected)
                  for kind, summary in SUPPORTS.items()),
            ]),
            "How a supporting skill helps this test. Rules set its difficulty.",
        )
        self.ratings_input = self.field(
            "Supporting skill rating",
            discord.ui.TextInput(
                default=draft.get("ratings", ", ".join(map(str, support.ratings)) if support else ""),
                required=False, max_length=60, placeholder="e.g. 75; Rally takes up to three, e.g. 50, 75, 25",
            ),
            "Unmodified, like your skill rating.",
        )
        self.names_input = self.field(
            "Supporting skill name (optional)",
            discord.ui.TextInput(
                default=draft.get("names", ", ".join(support.names) if support else ""), required=False,
                max_length=100, placeholder="e.g. Acrobatics; for Rally, e.g. Climb, Swim, Jump",
            ),
        )

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.setup.interaction_check(interaction):
            return
        selected = self.kind_input.values
        kind = selected[0] if selected else next(
            option.value for option in self.kind_input.options if option.default
        )
        draft = {"kind": kind, "ratings": self.ratings_input.value.strip(), "names": self.names_input.value.strip()}
        self.setup.drafts[self.draft_key] = draft
        try:
            support = None if kind == "None" else parse_support(kind, draft["ratings"], draft["names"])
        except ValueError as error:
            button = "Opponent support" if self.opponent else "Your support"
            await self.setup.show_panel(
                interaction, error=f"{error} Click **{button}** to correct it; your entries are saved."
            )
            return
        (self.setup.opponent if self.opponent else self.setup.your).support = support
        del self.setup.drafts[self.draft_key]
        await self.setup.show_panel(interaction)


class RollSetupView(discord.ui.View):
    def __init__(
        self, owner_id: int, your: Participant, opponent: Optional[Participant] = None,
        comment: str = "",
    ):
        super().__init__(timeout=SETUP_TIMEOUT)
        self.owner_id = owner_id
        self.your = your
        self.opponent = opponent
        self.comment = comment
        self.default_names = {"your": your.name, "opponent": opponent.name if opponent else "Your opponent"}
        self.drafts = {}
        self.message = None
        self.finished = False
        if opponent is None:
            self.remove_item(self.edit_opponent)
            self.remove_item(self.edit_opponent_support)
        self.roll_button.disabled = your.skill_rating is None

    @property
    def command_name(self) -> str:
        return "opposed" if self.opponent is not None else "tiered"

    async def start(self, interaction: discord.Interaction):
        if self.opponent is None:
            await interaction.response.send_modal(ParticipantModal(self))
        else:
            await self.show_panel(interaction)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Start your own test to edit its details.", ephemeral=True)
            return False
        if self.finished or self.is_finished():
            await interaction.response.send_message(
                f"This setup has closed. Run `/{self.command_name}` to start another test.", ephemeral=True
            )
            return False
        return True

    def participant_summary(self, participant: Participant, *, opponent: bool = False) -> str:
        if participant.skill_rating is None:
            return (
                "No opponent entered. Add their details, or leave blank to roll only your side."
                if opponent else "Click **Your details** to enter your skill rating."
            )
        safe_name = discord.utils.escape_markdown(participant.name)
        lines = [f"**{safe_name}**"]
        if participant.skill_name:
            lines.append(f"Skill: {discord.utils.escape_markdown(participant.skill_name)}")
        difficulty = participant.difficulty.name.replace("_", " ").title()
        lines.append(f"Rating: **{participant.skill_rating}** | Modifier: **{participant.modifier:+d}**")
        if participant.difficulty in (Difficulty.AUTOMATIC, Difficulty.IMPOSSIBLE):
            lines.append(f"Difficulty: **{difficulty}** — no die roll")
        else:
            target = modify_skill_rating(participant.skill_rating, participant.difficulty, participant.modifier)
            lines.append(f"Difficulty: **{difficulty}** | Target: **{target}**")
            if participant.roll is not None:
                lines.append(f"Manual roll: **{participant.roll}**")
            else:
                lines.append("Roll: random d100")
        if participant.support is not None:
            support = participant.support
            skills = ", ".join(
                f"{discord.utils.escape_markdown(name)} (**{rating}**)" if name else f"**{rating}**"
                for rating, name in zip(support.ratings, support.names + [""] * len(support.ratings))
            )
            lines.append(f"Support: **{support.kind}** with {skills}")
        return "\n".join(lines)

    def summary(self) -> discord.Embed:
        embed = discord.Embed(
            title="Opposed test" if self.opponent is not None else "Tiered test",
            description="Check your details, then press **Roll** to share the result in this channel.",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(name="Your details", value=self.participant_summary(self.your), inline=False)
        if self.opponent is not None:
            embed.add_field(
                name="Opponent details", value=self.participant_summary(self.opponent, opponent=True), inline=False
            )
        if self.comment:
            # Embed fields have a 1024-character limit; escaping can double the length.
            comment = discord.utils.escape_markdown(self.comment)
            embed.description += f"\n\n**Test:** {comment}"
        if self.drafts:
            labels = {
                "your": "Your details", "opponent": "Opponent details", "advanced": "Advanced options",
                "your_support": "Your support", "opponent_support": "Opponent support",
            }
            pending = ", ".join(labels[key] for key in self.drafts)
            embed.description += f"\n\nCorrect the saved entries in **{pending}** before rolling."
        embed.set_footer(text="Only you can see this setup. It closes after 10 minutes of inactivity.")
        return embed

    async def show_panel(self, interaction: discord.Interaction, error: Optional[str] = None):
        self.roll_button.disabled = self.your.skill_rating is None or bool(self.drafts)
        kwargs = dict(content=error, embed=self.summary(), view=self, allowed_mentions=discord.AllowedMentions.none())
        if self.message is None:
            await interaction.response.send_message(**kwargs, ephemeral=True)
        else:
            await interaction.response.edit_message(**kwargs)
        self.message = await interaction.original_response()

    @discord.ui.button(label="Your details", style=discord.ButtonStyle.primary, row=0)
    async def edit_your(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ParticipantModal(self))

    @discord.ui.button(label="Opponent details", style=discord.ButtonStyle.primary, row=0)
    async def edit_opponent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ParticipantModal(self, opponent=True))

    @discord.ui.button(label="Advanced options", style=discord.ButtonStyle.secondary, row=0)
    async def edit_advanced(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AdvancedModal(self))

    @discord.ui.button(label="Your support", style=discord.ButtonStyle.secondary, row=1)
    async def edit_your_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SupportModal(self))

    @discord.ui.button(label="Opponent support", style=discord.ButtonStyle.secondary, row=1)
    async def edit_opponent_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SupportModal(self, opponent=True))

    @discord.ui.button(label="Roll", style=discord.ButtonStyle.success, row=2)
    async def roll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.submit_roll(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.finished = True
        self.stop()
        await interaction.response.edit_message(content="Test cancelled.", embed=None, view=None)

    async def submit_roll(self, interaction: discord.Interaction):
        if not await self.interaction_check(interaction):
            return
        if self.your.skill_rating is None or self.drafts:
            await interaction.response.send_message("Complete or correct your details before rolling.", ephemeral=True)
            return
        try:
            # Slash arguments can prefill a guide, so validate those manual rolls too.
            parse_roll("" if self.your.roll is None else str(self.your.roll), "Your manual roll")
            if self.opponent is not None and self.opponent.skill_rating is not None:
                parse_roll("" if self.opponent.roll is None else str(self.opponent.roll), "Opponent's manual roll")
        except ValueError as error:
            await self.show_panel(interaction, error=f"{error} Click **Advanced options** to correct it.")
            return
        # Support depends on details that can change after it is chosen, so check it only now.
        for participant, button in ((self.your, "Your support"), (self.opponent, "Opponent support")):
            if participant is not None and participant.skill_rating is not None and participant.support is not None:
                problem = support_problem(participant.skill_rating, participant.difficulty, participant.support)
                if problem:
                    await self.show_panel(interaction, error=f"{problem} Click **{button}** to correct it.")
                    return
        # Set before the first await so double clicks cannot publish two rolls.
        self.finished = True
        try:
            await RollResultView(self.your, self.opponent, self.comment).send(interaction)
        except Exception:
            self.finished = False
            raise
        self.stop()
        if self.message is not None:
            try:
                await self.message.edit(content="Result posted to the channel.", embed=None, view=None)
            except discord.HTTPException:
                log.warning("Could not close the setup message after posting a roll.", exc_info=True)

    async def on_timeout(self):
        self.finished = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content=f"This setup expired. Run `/{self.command_name}` to start again.", embed=None, view=None
                )
            except discord.HTTPException:
                pass  # The ephemeral message may have been dismissed or its token expired.

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        if log_expired_interaction(interaction, error):
            return
        log.error("Guided roll failed", exc_info=(type(error), error, error.__traceback__))
        message = f"I couldn't complete that action. Try again, or run `/{self.command_name}` for a new setup."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.NotFound as response_error:
            if not log_expired_interaction(interaction, response_error):
                raise


def message_kwargs(text: str) -> dict:
    # Long names and comments can push a result past Discord's 2000-character message limit.
    long = len(text) > 2000
    return {
        "content": None if long else text,
        "embed": discord.Embed(description=text) if long else None,
        "allowed_mentions": discord.AllowedMentions.none(),
    }


class RollResultView(discord.ui.View):
    """A posted result where each participant may once reroll, flip, or force the opponent to reroll."""

    def __init__(self, your: Participant, opponent: Optional[Participant] = None, comment: str = ""):
        # ponytail: buttons live in memory and close after 10 minutes, inside the 15-minute token that
        # removes them; use persistent views if play-by-post needs longer or buttons must survive restarts.
        super().__init__(timeout=SETUP_TIMEOUT)
        # Roll copies now, so every change rebuilds the result from the same criteria. Buttons change only
        # the main roll; supporting dice stay, and are read only if the new main roll calls for them.
        self.your, self.opponent = (
            None if p is None else replace(
                p, roll=random.randint(1, 100) if p.roll is None else p.roll,
                support=p.support and replace(p.support, rolls=[random.randint(1, 100) for _ in p.support.ratings]),
            )
            for p in (your, opponent)
        )
        self.comment = comment
        self.changes = []
        self.interaction = None
        sides = [p for p in (self.your, self.opponent) if p is not None and p.skill_rating is not None]
        for row, actor in enumerate(sides):
            actions = [(actor, "Reroll"), (actor, "Flip")]
            actions += [(other, f"Force {other.name[:30]} to reroll") for other in sides if other is not actor]
            for target, action in actions:
                if target.difficulty not in (Difficulty.AUTOMATIC, Difficulty.IMPOSSIBLE):
                    button = discord.ui.Button(label=f"{actor.name[:30]}: {action}", row=row)
                    button.callback = partial(self.change, row=row, actor=actor, target=target, flipped=action == "Flip")
                    self.add_item(button)

    def result(self) -> str:
        your = self.your
        if self.opponent is None:
            return build_tiered_result(
                skill_rating=your.skill_rating, difficulty=your.difficulty, modifier=your.modifier,
                roll=your.roll, your_name=your.name, comment=self.comment, skill_name=your.skill_name,
                support=your.support,
            )
        opponent = self.opponent
        return build_opposed_result(
            your_skill_rating=your.skill_rating, your_difficulty=your.difficulty,
            your_modifier=your.modifier, your_roll=your.roll, your_name=your.name,
            your_skill_name=your.skill_name, opponent_skill_rating=opponent.skill_rating,
            opponent_difficulty=opponent.difficulty, opponent_modifier=opponent.modifier,
            opponent_roll=opponent.roll, opponent_name=opponent.name,
            opponent_skill_name=opponent.skill_name, comment=self.comment,
            your_support=your.support, opponent_support=opponent.support,
        )

    def text(self) -> str:
        result = self.result().rstrip()
        return result + "\n\n" + "\n".join(self.changes) if self.changes else result

    async def send(self, interaction: discord.Interaction):
        self.interaction = interaction
        # send_message rejects view=None, so a result with nothing to change posts without one.
        await interaction.response.send_message(
            **message_kwargs(self.text()), view=self if self.children else discord.utils.MISSING
        )

    async def change(
        self, interaction: discord.Interaction, *, row: int, actor: Participant, target: Participant, flipped: bool,
    ):
        buttons = [item for item in self.children if item.row == row]
        if not buttons:
            # A quick second click can arrive before Discord hides the used buttons.
            await interaction.response.send_message(f"**{actor.name}** has already changed this roll.", ephemeral=True)
            return
        old = target.roll
        verb = "flipped" if flipped else "rerolled" if target is actor else f"forced **{target.name}** to reroll"
        # Apply before the first await so a double click cannot change the roll twice.
        target.roll = flip_roll(old) if flipped else random.randint(1, 100)
        change = f"**{actor.name}** {verb}: **{old}** → **{target.roll}**"
        self.changes.append(change)
        for item in buttons:
            self.remove_item(item)
        try:
            await interaction.response.edit_message(
                **message_kwargs(self.text()), view=self if self.children else None
            )
        except Exception:
            # Undo, so a click Discord rejected can be retried.
            target.roll = old
            self.changes.remove(change)
            for item in buttons:
                self.add_item(item)
            raise
        self.interaction = interaction
        if not self.children:
            self.stop()

    async def on_timeout(self):
        try:
            await self.interaction.edit_original_response(view=None)
        except discord.HTTPException:
            pass  # The result may have been deleted.

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        if not log_expired_interaction(interaction, error):
            await super().on_error(interaction, error, item)
