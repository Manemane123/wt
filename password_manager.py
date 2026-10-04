"""Daily password rotation on Dallas time (America/Chicago).

State is persisted to password.json so the Flask app and the Telegram bot
see the same value. rotate_if_needed() is called by the bot's scheduler
once a minute and, when the Dallas date rolls over, generates a new
password and edits the pinned channel post so subscribers see it.
"""

import os
import json
import secrets
import string
from datetime import datetime, timezone, timedelta

# Bot / channel wiring
CHANNEL = "-1001192930889"
CHANNEL_ID = "1192930889"
PASSWORD_POST_MSG_ID = 610

# Public site URL that appears in the channel post
SITE_URL = os.getenv("SITE_URL", "https://justrunmy.app")

PASSWORD_FILE = os.path.join(os.path.dirname(__file__), "password.json")

# America/Chicago: CST=UTC-6, CDT=UTC-5. python-telegram-bot pulls tzdata via
# python's zoneinfo, but to avoid extra deps we approximate with the
# US DST rule (2nd Sun Mar -> 1st Sun Nov).
def _dallas_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago"))
    except Exception:
        # Fallback: naive DST calc
        u = datetime.now(timezone.utc)
        y = u.year
        # 2nd Sunday March
        d = datetime(y, 3, 8, 7, tzinfo=timezone.utc)
        while d.weekday() != 6:
            d += timedelta(days=1)
        dst_start = d
        # 1st Sunday November
        d = datetime(y, 11, 1, 6, tzinfo=timezone.utc)
        while d.weekday() != 6:
            d += timedelta(days=1)
        dst_end = d
        offset = -5 if dst_start <= u < dst_end else -6
        return u + timedelta(hours=offset)


def _generate_password():
    # 12 chars A-Z0-9, grouped 4-4-4 for readability
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


def _load():
    try:
        with open(PASSWORD_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(state):
    tmp = PASSWORD_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, PASSWORD_FILE)


def get_current_password():
    state = _load()
    if "password" not in state:
        state = {"password": _generate_password(),
                 "date": _dallas_now().strftime("%Y-%m-%d")}
        _save(state)
    return state["password"]


def get_password_url():
    return f"https://t.me/c/{CHANNEL_ID}/{PASSWORD_POST_MSG_ID}"


def build_channel_post(password):
    return (
        "Affiliate Marketing Website\n"
        "<blockquote>\n"
        "With our website you can show products to your friends and family "
        "who are not in our menu!\n\n"
        "Prices are not listed. We encourage everyone to take advantage and "
        "make money!💰\n"
        "</blockquote>\n\n"
        f"🔗 <a href=\"{SITE_URL}\">{SITE_URL}</a>\n\n"
        f"PASSWORD: <code>{password}</code>\n\n"
        "PASSWORD CHANGES EVERY 24 HOURS!"
    )


async def rotate_if_needed(bot, force=False):
    """Called from the bot scheduler. Rotates the password if the Dallas
    date has changed (or force=True), then edits the channel post."""
    today = _dallas_now().strftime("%Y-%m-%d")
    state = _load()
    changed = force or state.get("date") != today or "password" not in state
    if changed:
        state = {"password": _generate_password(), "date": today}
        _save(state)
        print(f"[password] rotated: date={today}")

    # Always try to edit so the post stays in sync even if we restarted
    text = build_channel_post(state["password"])
    try:
        await bot.edit_message_text(
            chat_id=CHANNEL,
            message_id=PASSWORD_POST_MSG_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        print(f"[password] channel post {PASSWORD_POST_MSG_ID} updated")
    except Exception as e:
        msg = str(e)
        if "not modified" in msg.lower():
            pass
        elif "no text in the message" in msg.lower():
            try:
                await bot.edit_message_caption(
                    chat_id=CHANNEL,
                    message_id=PASSWORD_POST_MSG_ID,
                    caption=text,
                    parse_mode="HTML",
                )
                print(f"[password] channel post {PASSWORD_POST_MSG_ID} caption updated")
            except Exception as e2:
                if "not modified" not in str(e2).lower():
                    print(f"[password] caption edit error: {e2}")
        else:
            print(f"[password] channel edit error: {e}")
    return state["password"]
