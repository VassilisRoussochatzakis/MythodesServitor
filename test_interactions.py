"""Offline regression checks for Discord interaction expiry handling."""

from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

import roll_ui

# Command tests neither need the real credential nor start the client.
with patch.dict("sys.modules", {"constants": SimpleNamespace(BOT_TOKEN="unused-test-token")}):
    import bot


def not_found(code=10062):
    return discord.NotFound(
        SimpleNamespace(status=404, reason="Not Found"),
        {"code": code, "message": "Unknown interaction"},
    )


def interaction(*, responded=False):
    return SimpleNamespace(
        id=123,
        created_at=discord.utils.utcnow() - timedelta(seconds=4),
        command=bot.tiered,
        type=discord.InteractionType.application_command,
        data={"name": "tiered"},
        client=SimpleNamespace(latency=0.125),
        user=SimpleNamespace(id=42, display_name="Player"),
        response=SimpleNamespace(
            is_done=Mock(return_value=responded),
            send_modal=AsyncMock(), send_message=AsyncMock(), edit_message=AsyncMock(), defer=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )


class InteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_guided_tiered_opens_modal_without_deferring(self):
        current = interaction()
        await bot.tiered.callback(current)
        current.response.send_modal.assert_awaited_once()
        modal = current.response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, roll_ui.ParticipantModal)
        self.assertEqual(modal.setup.owner_id, current.user.id)
        current.response.defer.assert_not_awaited()
        current.response.send_message.assert_not_awaited()

    async def test_direct_opposed_result_over_2000_characters_uses_embed(self):
        for length, key in ((2000, "content"), (2001, "embed")):
            with self.subTest(length=length), patch.object(roll_ui, "build_opposed_result", return_value="x" * length):
                current = interaction()
                await bot.opposed.callback(current, your_skill_rating=50)
                kwargs = current.response.send_message.await_args.kwargs
                self.assertEqual([name for name in ("content", "embed") if kwargs[name] is not None], [key])

    async def test_each_participant_changes_a_posted_roll_once(self):
        view = roll_ui.RollResultView(roll_ui.Participant("Ann", 50, roll=71), roll_ui.Participant("Bob", 40, roll=20))
        self.assertEqual([button.label for button in view.children], [
            "Ann: Reroll", "Ann: Flip", "Ann: Force Bob to reroll",
            "Bob: Reroll", "Bob: Flip", "Bob: Force Ann to reroll",
        ])
        ann_flip, bob_force = view.children[1], view.children[5]
        rejected = interaction()
        rejected.response.edit_message.side_effect = not_found()
        with self.assertRaises(discord.NotFound):
            await ann_flip.callback(rejected)
        self.assertEqual((view.your.roll, len(view.children), view.changes), (71, 6, []))

        await ann_flip.callback(interaction())
        stale = interaction()
        await ann_flip.callback(stale)
        stale.response.send_message.assert_awaited_once()
        self.assertEqual((view.your.roll, len(view.children)), (17, 3))

        current = interaction()
        with patch("roll_ui.random.randint", return_value=5):
            await bob_force.callback(current)
        kwargs = current.response.edit_message.await_args.kwargs
        self.assertIn("**Ann** flipped: **71** → **17**\n**Bob** forced **Ann** to reroll: **17** → **5**", kwargs["content"])
        self.assertIsNone(kwargs["view"])
        self.assertTrue(view.is_finished())
        no_die = roll_ui.Participant("Ann", 50, roll_ui.Difficulty.AUTOMATIC)
        self.assertEqual(roll_ui.RollResultView(no_die).children, [])

    async def test_only_unknown_interaction_is_classified_as_expired(self):
        current = interaction()
        with patch("roll_ui.discord.utils.utcnow", return_value=current.created_at + timedelta(seconds=4)), \
                self.assertLogs(roll_ui.log, level="WARNING") as captured:
            self.assertTrue(roll_ui.log_expired_interaction(current, not_found()))
        self.assertIn("4.00s", captured.output[0])
        self.assertIn("125ms", captured.output[0])
        for error in (not_found(10008), ValueError("invalid details"),
                      discord.HTTPException(SimpleNamespace(status=400, reason="Bad Request"),
                                            {"code": 10062, "message": "Unknown interaction"})):
            with self.subTest(error=type(error).__name__), self.assertNoLogs(roll_ui.log):
                self.assertFalse(roll_ui.log_expired_interaction(current, error))

    async def test_wrapped_command_expiry_does_not_retry_response(self):
        current = interaction()
        current.response.send_modal.side_effect = not_found()
        with self.assertRaises(discord.NotFound) as raised:
            await bot.tiered.callback(current)
        wrapped = app_commands.CommandInvokeError(bot.tiered, raised.exception)
        self.assertIs(bot.client.tree.on_error, bot.on_app_command_error)
        with self.assertLogs(roll_ui.log, level="WARNING"):
            await bot.on_app_command_error(current, wrapped)
        current.response.send_modal.assert_awaited_once()
        current.response.send_message.assert_not_awaited()
        current.response.defer.assert_not_awaited()
        current.followup.send.assert_not_awaited()

    async def test_other_command_errors_keep_default_handler(self):
        current = interaction()
        for error in (app_commands.CheckFailure("not allowed"),
                      app_commands.CommandInvokeError(bot.tiered, not_found(10008))):
            with self.subTest(error=type(error).__name__), patch.object(
                app_commands.CommandTree, "on_error", new_callable=AsyncMock,
            ) as handler:
                await bot.on_app_command_error(current, error)
                handler.assert_awaited_once_with(bot.client.tree, current, error)

    async def test_view_expiry_does_not_try_to_send_error_message(self):
        view = roll_ui.RollSetupView(42, roll_ui.Participant("Player"))
        current = interaction()
        with self.assertLogs(roll_ui.log, level="WARNING"):
            await view.on_error(current, not_found(), None)
        current.response.send_message.assert_not_awaited()
        current.followup.send.assert_not_awaited()

    async def test_regular_view_error_still_reports_privately(self):
        view = roll_ui.RollSetupView(42, roll_ui.Participant("Player"))
        for responded in (False, True):
            with self.subTest(responded=responded):
                current = interaction(responded=responded)
                with self.assertLogs(roll_ui.log, level="ERROR"):
                    await view.on_error(current, ValueError("invalid details"), None)
                sender = current.followup.send if responded else current.response.send_message
                sender.assert_awaited_once()
                self.assertTrue(sender.await_args.kwargs["ephemeral"])

    async def test_error_notification_expiry_is_handled_but_other_404s_propagate(self):
        view = roll_ui.RollSetupView(42, roll_ui.Participant("Player"))
        for responded in (False, True):
            for code in (10062, 10008):
                with self.subTest(responded=responded, code=code):
                    current = interaction(responded=responded)
                    sender = current.followup.send if responded else current.response.send_message
                    sender.side_effect = not_found(code)
                    with self.assertLogs(roll_ui.log, level="WARNING"):
                        if code == 10062:
                            await view.on_error(current, ValueError("invalid details"), None)
                        else:
                            with self.assertRaises(discord.NotFound):
                                await view.on_error(current, ValueError("invalid details"), None)
                    sender.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
