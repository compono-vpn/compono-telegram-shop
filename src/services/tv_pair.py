"""TV pairing in the bot (COM-202, TV pairing contract v1).

The TV shows a QR code for ``t.me/compono_bot?start=tv-<CODE>``. The bot does not
claim on /start: it first asks the user to confirm that this exact code is on their
TV screen (so a stranger cannot send a victim the QR of the stranger's TV), and only
the confirm button calls compono-api's internal claim. compono-api checks the
subscription; the bot never sees a subscription URL.
"""

from __future__ import annotations

import re
from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.core.constants import TV_PAIR_CANCEL, TV_PAIR_CONFIRM_PREFIX, TV_PAIR_PREFIX

# Crockford base32 upper case: no I, L, O, U.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CODE = f"[{CODE_ALPHABET}]{{8}}"
# re.ASCII: without it IGNORECASE also folds KELVIN SIGN onto K and LONG S onto S, so a
# typed look-alike passed as a code whose button the callback parser then refused (QA round 3).
START_PARAM_RE = re.compile(rf"^{re.escape(TV_PAIR_PREFIX)}{_CODE}$", re.IGNORECASE | re.ASCII)
# /start (optionally /start@bot) followed by exactly one tv-<CODE> payload.
START_TEXT_RE = re.compile(
    rf"^/start(?:@\w+)?\s+{re.escape(TV_PAIR_PREFIX)}{_CODE}\s*$", re.IGNORECASE | re.ASCII
)
_CODE_RE = re.compile(rf"^{_CODE}$")


def code_from_start_param(param: Optional[str]) -> Optional[str]:
    """``tv-k7m4qx9p`` -> ``K7M4QX9P``; None for anything that is not a TV payload."""
    if not param or not START_PARAM_RE.match(param.strip()):
        return None
    return param.strip()[len(TV_PAIR_PREFIX) :].upper()


def code_from_start_text(text: Optional[str]) -> Optional[str]:
    if not text or not START_TEXT_RE.match(text):
        return None
    return code_from_start_param(text.split()[1])


def code_from_callback(data: Optional[str]) -> Optional[str]:
    """``tvp:K7M4QX9P`` -> ``K7M4QX9P``; None for a malformed or forged button."""
    if not data or not data.startswith(TV_PAIR_CONFIRM_PREFIX):
        return None
    code = data[len(TV_PAIR_CONFIRM_PREFIX) :]
    return code if _CODE_RE.match(code) else None


def display_code(code: str) -> str:
    """``K7M4QX9P`` -> ``K7M4-QX9P``, as the TV shows it."""
    return f"{code[:4]}-{code[4:]}"


def log_code(code: str) -> str:
    """The only form of a code that may be logged: its first two characters."""
    return f"{code[:2]}******" if len(code) > 2 else "**"


def confirm_keyboard(code: str, confirm_text: str, cancel_text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=confirm_text, callback_data=TV_PAIR_CONFIRM_PREFIX + code)],
            [InlineKeyboardButton(text=cancel_text, callback_data=TV_PAIR_CANCEL)],
        ]
    )


def retry_keyboard(code: str, retry_text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=retry_text, callback_data=TV_PAIR_CONFIRM_PREFIX + code)],
        ]
    )
