from typing import Optional
from constants import BOT_TOKEN

import discord
from discord import app_commands

from rolls import (
    Difficulty,
    Tier,
    build_opposed_result,
    build_tiered_result,
    format_test_result,
    get_victory_magnitude,
    modify_skill_rating,
    resolve_test,
)
from roll_ui import Participant, RollSetupView, log_expired_interaction


class MyClient(discord.Client):
    # Suppress error on the User attribute being None since it fills up later
    user: discord.ClientUser

    def __init__(self, *, intents: discord.Intents):
        # Names and comments are user-typed, so replies must never ping anyone.
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


intents = discord.Intents.default()
client = MyClient(intents=intents)


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
    if log_expired_interaction(interaction, original):
        return
    await app_commands.CommandTree.on_error(client.tree, interaction, error)


@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('------')


@client.tree.command()
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f'Pong! {round(interaction.client.latency * 1000)} ms')

@client.tree.command(description="Run a skill test; omit the skill rating for guided setup.")
@app_commands.describe(
    skill_rating='Your unmodified skill value (leave blank for guided setup)',
    difficulty='The difficulty of your test',
    modifier='Your flat modifier',
    roll='Force a specific roll',
    your_name='Your name for this test (defaults to your Discord display name)',
    skill_name='The skill you are testing (display only)',
    comment='What this test is for')
async def tiered(
    interaction: discord.Interaction,
    skill_rating: Optional[int] = None,
    difficulty: Optional[Difficulty] = Difficulty.STANDARD,
    modifier: Optional[int] = 0,
    roll: Optional[int] = None,
    your_name: Optional[app_commands.Range[str, 1, 100]] = None,
    comment: Optional[app_commands.Range[str, 1, 1000]] = None,
    skill_name: Optional[app_commands.Range[str, 1, 100]] = None):
    your_name = your_name or interaction.user.display_name
    if skill_rating is None:
        view = RollSetupView(
            owner_id=interaction.user.id,
            your=Participant(
                name=your_name,
                skill_rating=skill_rating,
                difficulty=difficulty,
                modifier=modifier,
                roll=roll,
                skill_name=skill_name or "",
            ),
            comment=comment or "",
        )
        await view.start(interaction)
        return

    results_str = build_tiered_result(
        skill_rating=skill_rating,
        difficulty=difficulty,
        modifier=modifier,
        roll=roll,
        your_name=your_name,
        comment=comment,
        skill_name=skill_name,
    )
    await interaction.response.send_message(results_str)

@client.tree.command(description="Compare opposed tests; omit your skill rating for guided setup.")
@app_commands.describe(
    your_skill_rating='Your unmodified skill value (leave blank for guided setup)',
    your_difficulty='The difficulty of your test',
    your_modifier='Your flat modifier',
    your_roll='Force a specific roll',
    opponent_skill_rating='Opponent\'s unmodified skill value',
    opponent_difficulty='Opponent\'s test difficulty',
    opponent_modifier='Opponent\'s flat modifier',
    opponent_roll='Force a specific roll',
    your_name='Your name for this test (defaults to your Discord display name)',
    opponent_name='Your opponent\'s name for this test',
    your_skill_name='The skill you are testing (display only)',
    opponent_skill_name='The skill your opponent is testing (display only)',
    comment='What this test is for')
async def opposed(
    interaction: discord.Interaction,
    your_skill_rating: Optional[int] = None,
    your_difficulty: Optional[Difficulty] = Difficulty.STANDARD,
    your_modifier: Optional[int] = 0,
    your_roll: Optional[int] = None,
    opponent_skill_rating: Optional[int] = None,
    opponent_difficulty: Optional[Difficulty] = Difficulty.STANDARD,
    opponent_modifier: Optional[int] = 0,
    opponent_roll: Optional[int] = None,
    your_name: Optional[app_commands.Range[str, 1, 100]] = None,
    opponent_name: Optional[app_commands.Range[str, 1, 100]] = None,
    comment: Optional[app_commands.Range[str, 1, 1000]] = None,
    your_skill_name: Optional[app_commands.Range[str, 1, 100]] = None,
    opponent_skill_name: Optional[app_commands.Range[str, 1, 100]] = None):
    your_name = your_name or interaction.user.display_name
    opponent_name = opponent_name or "Your opponent"
    if your_skill_rating is None:
        view = RollSetupView(
            owner_id=interaction.user.id,
            your=Participant(
                name=your_name,
                skill_rating=your_skill_rating,
                difficulty=your_difficulty,
                modifier=your_modifier,
                roll=your_roll,
                skill_name=your_skill_name or "",
            ),
            opponent=Participant(
                name=opponent_name,
                skill_rating=opponent_skill_rating,
                difficulty=opponent_difficulty,
                modifier=opponent_modifier,
                roll=opponent_roll,
                skill_name=opponent_skill_name or "",
            ),
            comment=comment or "",
        )
        await view.start(interaction)
        return

    final_output = build_opposed_result(
        your_skill_rating=your_skill_rating,
        your_difficulty=your_difficulty,
        your_modifier=your_modifier,
        your_roll=your_roll,
        opponent_skill_rating=opponent_skill_rating,
        opponent_difficulty=opponent_difficulty,
        opponent_modifier=opponent_modifier,
        opponent_roll=opponent_roll,
        your_name=your_name,
        opponent_name=opponent_name,
        comment=comment,
        your_skill_name=your_skill_name,
        opponent_skill_name=opponent_skill_name,
    )
    # Long names and comments can push this past Discord's 2000-character message limit.
    kwargs = {"content": final_output} if len(final_output) <= 2000 else {"embed": discord.Embed(description=final_output)}
    await interaction.response.send_message(**kwargs)


if __name__ == '__main__':
    client.run(BOT_TOKEN)
