"""
=====================================================================
 SESSION STRING GENERATOR BOT (Pyrogram + Telethon) - Single File
=====================================================================

WHAT THIS IS
-------------
A Telegram bot that lets a user generate their own Pyrogram session
string OR Telethon session string by logging in with their phone
number, OTP code, and (if enabled) 2FA password. Nothing is stored
on disk - everything happens in memory and the session string is
sent back to the user in a private chat, then the bot forgets it.

REQUIRED ENV VARS (set these as Heroku Config Vars)
-----------------------------------------------------
    API_ID       -> your api_id from https://my.telegram.org
    API_HASH     -> your api_hash from https://my.telegram.org
    BOT_TOKEN    -> bot token from @BotFather

    (API_ID/API_HASH here are only used to run the BOT itself.
     The user's own API_ID/API_HASH -- which they will be asked
     for in chat -- are used to generate THEIR session string.)

FILES YOU NEED FOR HEROKU DEPLOYMENT
--------------------------------------
1) This file, named e.g. bot.py

2) requirements.txt
   ---------------------------------
   pyrogram==2.0.106
   tgcrypto==1.2.5
   telethon==1.36.0
   ---------------------------------

3) Procfile   (bot uses polling, so it must run as a WORKER dyno)
   ---------------------------------
   worker: python bot.py
   ---------------------------------

4) runtime.txt   (optional, pin python version)
   ---------------------------------
   python-3.11.9
   ---------------------------------

DEPLOY STEPS
-------------
    heroku create your-app-name
    heroku config:set API_ID=123456 API_HASH=xxxx BOT_TOKEN=xxxx
    git add .
    git commit -m "session gen bot"
    git push heroku main
    heroku ps:scale worker=1

USAGE (from the end user's side, in the bot's private chat)
--------------------------------------------------------------
    /start          -> shows buttons: Pyrogram / Telethon
    choose one       -> bot asks for API_ID, API_HASH, phone number,
                        OTP code (and 2FA password if needed)
    /cancel          -> cancel/reset at any point

SECURITY NOTES
----------------
- Session strings grant FULL account access. Only run this bot if
  you trust it, and never share the resulting string with anyone.
- The bot deletes the message containing the OTP/password from the
  chat right after reading it, to reduce the chance of it lingering.
- All state is kept in memory (a plain dict) - if the dyno restarts
  mid-login, the user just needs to start over with /start.
=====================================================================
"""

import asyncio
import logging
import os

from pyrogram import Client, filters, idle
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PasswordHashInvalid,
    FloodWait,
)

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("session-gen-bot")

# ---------------------------------------------------------------------
# Config (from environment)
# ---------------------------------------------------------------------
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

# ---------------------------------------------------------------------
# In-memory per-user conversation state
# ---------------------------------------------------------------------
# user_id -> {
#   "mode": "pyrogram" | "telethon",
#   "stage": "api_id" | "api_hash" | "phone" | "code" | "password",
#   "api_id": int,
#   "api_hash": str,
#   "phone": str,
#   "client": <Pyrogram Client or Telethon TelegramClient>,
#   "phone_code_hash": str,   # telethon needs this explicitly
# }
STATE = {}


def reset_user(user_id: int):
    STATE.pop(user_id, None)


async def safe_delete(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


# ---------------------------------------------------------------------
# Bot client
# ---------------------------------------------------------------------
bot = Client(
    "session_gen_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)


# ---------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------
@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(_, message: Message):
    reset_user(message.from_user.id)
    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Pyrogram Session", callback_data="mode_pyrogram"),
                InlineKeyboardButton("Telethon Session", callback_data="mode_telethon"),
            ]
        ]
    )
    await message.reply_text(
        "**Session String Generator**\n\n"
        "Choose which type of session string you want to generate.\n"
        "You'll need your own `api_id` / `api_hash` from "
        "https://my.telegram.org and your phone number.\n\n"
        "Use /cancel anytime to stop.\n\n"
        "⚠️ A session string gives full access to your account. "
        "Only generate one for yourself, and never share it.",
        reply_markup=buttons,
        disable_web_page_preview=True,
    )


@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(_, message: Message):
    reset_user(message.from_user.id)
    await message.reply_text("Cancelled. Send /start to begin again.")


# ---------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------
@bot.on_callback_query(filters.regex(r"^mode_(pyrogram|telethon)$"))
async def mode_chosen(_, cq: CallbackQuery):
    mode = cq.data.split("_", 1)[1]
    user_id = cq.from_user.id
    STATE[user_id] = {"mode": mode, "stage": "api_id"}
    await cq.message.edit_text(
        f"Generating a **{mode.capitalize()}** session string.\n\n"
        "Step 1/4 - Send me your **API_ID** (a number).\n"
        "Get it from https://my.telegram.org -> API Development Tools."
    )
    await cq.answer()


# ---------------------------------------------------------------------
# Main conversation handler (plain text messages, private chat only)
# ---------------------------------------------------------------------
@bot.on_message(filters.private & filters.text & ~filters.command(["start", "cancel"]))
async def conversation(_, message: Message):
    user_id = message.from_user.id
    if user_id not in STATE:
        return  # nothing in progress, ignore

    data = STATE[user_id]
    stage = data["stage"]
    text = message.text.strip()

    # ---------------- API_ID ----------------
    if stage == "api_id":
        if not text.isdigit():
            await message.reply_text("That doesn't look like a number. Send your **API_ID** again.")
            return
        data["api_id"] = int(text)
        data["stage"] = "api_hash"
        await message.reply_text("Step 2/4 - Now send me your **API_HASH**.")
        return

    # ---------------- API_HASH ----------------
    if stage == "api_hash":
        data["api_hash"] = text
        data["stage"] = "phone"
        await safe_delete(message)  # api_hash is semi-sensitive
        await message.reply_text(
            "Step 3/4 - Send your phone number in international format, "
            "e.g. `+15551234567`."
        )
        return

    # ---------------- PHONE ----------------
    if stage == "phone":
        phone = text
        data["phone"] = phone
        status = await message.reply_text("Sending OTP code, please wait...")

        try:
            if data["mode"] == "pyrogram":
                client = Client(
                    ":memory:",
                    api_id=data["api_id"],
                    api_hash=data["api_hash"],
                    in_memory=True,
                )
                await client.connect()
                sent = await client.send_code(phone)
                data["client"] = client
                data["phone_code_hash"] = sent.phone_code_hash

            else:  # telethon
                client = TelegramClient(
                    StringSession(), data["api_id"], data["api_hash"]
                )
                await client.connect()
                sent = await client.send_code_request(phone)
                data["client"] = client
                data["phone_code_hash"] = sent.phone_code_hash

            data["stage"] = "code"
            await status.edit_text(
                "Step 4/4 - Enter the code Telegram just sent you.\n\n"
                "⚠️ To stop Telegram's official apps from auto-invalidating "
                "the code, type it with a space or letter between digits, "
                "e.g. if the code is `12345` send it as `1 2 3 4 5`."
            )
        except FloodWait as e:
            await status.edit_text(f"Flood wait: try again in {e.value} seconds.")
            reset_user(user_id)
        except Exception as e:
            log.exception("send_code failed")
            await status.edit_text(f"Failed to send code: {e}\nSend /start to retry.")
            reset_user(user_id)
        return

    # ---------------- CODE ----------------
    if stage == "code":
        code = text.replace(" ", "").replace("-", "")
        await safe_delete(message)
        client = data["client"]
        status = await message.reply_text("Verifying code...")

        try:
            if data["mode"] == "pyrogram":
                await client.sign_in(
                    phone_number=data["phone"],
                    phone_code_hash=data["phone_code_hash"],
                    phone_code=code,
                )
                session_string = await client.export_session_string()
                await client.disconnect()
                await status.edit_text(
                    "✅ **Pyrogram session string:**\n\n"
                    f"`{session_string}`\n\n"
                    "Keep this private. Anyone with this string can log in as you."
                )
                reset_user(user_id)

            else:  # telethon
                await client.sign_in(
                    phone=data["phone"],
                    code=code,
                    phone_code_hash=data["phone_code_hash"],
                )
                session_string = client.session.save()
                await client.disconnect()
                await status.edit_text(
                    "✅ **Telethon session string:**\n\n"
                    f"`{session_string}`\n\n"
                    "Keep this private. Anyone with this string can log in as you."
                )
                reset_user(user_id)

        except (SessionPasswordNeeded, SessionPasswordNeededError):
            data["stage"] = "password"
            await status.edit_text(
                "Your account has 2FA enabled. Please send your **2FA password**."
            )
        except (PhoneCodeInvalid, PhoneCodeInvalidError):
            await status.edit_text("Invalid code. Send the correct code again.")
        except (PhoneCodeExpired, PhoneCodeExpiredError):
            await status.edit_text("Code expired. Send /start to try again.")
            reset_user(user_id)
        except Exception as e:
            log.exception("sign_in failed")
            await status.edit_text(f"Sign-in failed: {e}\nSend /start to retry.")
            reset_user(user_id)
        return

    # ---------------- 2FA PASSWORD ----------------
    if stage == "password":
        password = text
        await safe_delete(message)
        client = data["client"]
        status = await message.reply_text("Verifying password...")

        try:
            if data["mode"] == "pyrogram":
                await client.check_password(password)
                session_string = await client.export_session_string()
                await client.disconnect()
                await status.edit_text(
                    "✅ **Pyrogram session string:**\n\n"
                    f"`{session_string}`\n\n"
                    "Keep this private. Anyone with this string can log in as you."
                )
            else:  # telethon
                await client.sign_in(password=password)
                session_string = client.session.save()
                await client.disconnect()
                await status.edit_text(
                    "✅ **Telethon session string:**\n\n"
                    f"`{session_string}`\n\n"
                    "Keep this private. Anyone with this string can log in as you."
                )
            reset_user(user_id)

        except (PasswordHashInvalid, PasswordHashInvalidError):
            await status.edit_text("Wrong password. Try again.")
        except Exception as e:
            log.exception("2FA check failed")
            await status.edit_text(f"Failed: {e}\nSend /start to retry.")
            reset_user(user_id)
        return


# ---------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------
async def main():
    await bot.start()
    log.info("Bot started. Waiting for messages...")
    await idle()
    await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
