"""Tests for CommandService — verifies bot command setup and deletion per locale."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from src.core.enums import Command, Locale
from src.services.command import CommandService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(
    setup_commands: bool = True,
    locales: list[Locale] | None = None,
    default_locale: Locale = Locale.EN,
) -> tuple[CommandService, MagicMock, AsyncMock, MagicMock]:
    """Return (service, config, bot, translator_hub)."""
    config = MagicMock()
    config.bot.setup_commands = setup_commands
    config.locales = locales if locales is not None else [Locale.EN, Locale.RU]
    config.default_locale = default_locale

    bot = AsyncMock()
    redis_client = AsyncMock()
    redis_repository = AsyncMock()
    translator_hub = MagicMock()

    # Each call to get_translator_by_locale returns a mock i18n that returns "[key]"
    i18n_mock = MagicMock()
    i18n_mock.get.side_effect = lambda key, **kwargs: f"[{key}]"
    translator_hub.get_translator_by_locale.return_value = i18n_mock

    svc = CommandService(
        config=config,
        bot=bot,
        redis_client=redis_client,
        redis_repository=redis_repository,
        translator_hub=translator_hub,
    )
    return svc, config, bot, translator_hub


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------

class TestSetup:
    async def test_sets_commands_for_each_locale_plus_default(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.EN, Locale.RU])
        bot.set_my_commands.return_value = True

        await svc.setup()

        # Should be called for EN, RU, and None (default)
        assert bot.set_my_commands.await_count == 3

    async def test_skips_when_setup_disabled(self):
        svc, config, bot, translator_hub = _make_service(setup_commands=False)

        await svc.setup()

        bot.set_my_commands.assert_not_awaited()

    async def test_commands_contain_all_enum_values(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.EN])
        bot.set_my_commands.return_value = True

        await svc.setup()

        # First call is for Locale.EN
        first_call = bot.set_my_commands.call_args_list[0]
        commands = first_call[1]["commands"]

        command_names = {cmd.command for cmd in commands}
        expected_names = {cmd.value.command for cmd in Command}
        assert command_names == expected_names

    async def test_uses_default_locale_for_none_language_code(self):
        svc, config, bot, translator_hub = _make_service(
            locales=[Locale.RU],
            default_locale=Locale.EN,
        )
        bot.set_my_commands.return_value = True

        await svc.setup()

        # get_translator_by_locale should be called with Locale.RU and Locale.EN (for default)
        locale_calls = [
            c[1]["locale"] if "locale" in c[1] else c[0][0]
            for c in translator_hub.get_translator_by_locale.call_args_list
        ]
        assert Locale.RU in locale_calls
        assert Locale.EN in locale_calls  # default locale used for None

    async def test_handles_set_commands_failure(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.EN])
        bot.set_my_commands.return_value = False  # Failure

        # Should not raise
        await svc.setup()

        bot.set_my_commands.assert_awaited()

    async def test_sets_scope_to_all_private_chats(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.EN])
        bot.set_my_commands.return_value = True

        await svc.setup()

        for call_obj in bot.set_my_commands.call_args_list:
            scope = call_obj[1]["scope"]
            assert scope.type == "all_private_chats"

    async def test_passes_correct_language_codes(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.EN, Locale.RU])
        bot.set_my_commands.return_value = True

        await svc.setup()

        language_codes = [
            c[1]["language_code"] for c in bot.set_my_commands.call_args_list
        ]
        assert language_codes == [Locale.EN, Locale.RU, None]

    async def test_single_locale(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.RU])
        bot.set_my_commands.return_value = True

        await svc.setup()

        assert bot.set_my_commands.await_count == 2  # RU + default

    async def test_empty_locales_only_sets_default(self):
        svc, config, bot, translator_hub = _make_service(locales=[])
        bot.set_my_commands.return_value = True

        await svc.setup()

        assert bot.set_my_commands.await_count == 1  # Only None (default)


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------

class TestDelete:
    async def test_deletes_commands_for_each_locale_plus_default(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.EN, Locale.RU])
        bot.delete_my_commands.return_value = True

        await svc.delete()

        assert bot.delete_my_commands.await_count == 3  # EN, RU, None

    async def test_skips_when_setup_disabled(self):
        svc, config, bot, translator_hub = _make_service(setup_commands=False)

        await svc.delete()

        bot.delete_my_commands.assert_not_awaited()

    async def test_handles_delete_failure(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.EN])
        bot.delete_my_commands.return_value = False

        # Should not raise
        await svc.delete()

        bot.delete_my_commands.assert_awaited()

    async def test_passes_correct_language_codes(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.EN, Locale.RU])
        bot.delete_my_commands.return_value = True

        await svc.delete()

        language_codes = [
            c[1]["language_code"] for c in bot.delete_my_commands.call_args_list
        ]
        assert language_codes == [Locale.EN, Locale.RU, None]

    async def test_sets_scope_to_all_private_chats(self):
        svc, config, bot, translator_hub = _make_service(locales=[Locale.EN])
        bot.delete_my_commands.return_value = True

        await svc.delete()

        for call_obj in bot.delete_my_commands.call_args_list:
            scope = call_obj[1]["scope"]
            assert scope.type == "all_private_chats"

    async def test_empty_locales_only_deletes_default(self):
        svc, config, bot, translator_hub = _make_service(locales=[])
        bot.delete_my_commands.return_value = True

        await svc.delete()

        assert bot.delete_my_commands.await_count == 1
