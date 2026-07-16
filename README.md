# Session String Generator Bot

Telegram bot that generates **Pyrogram** and **Telethon** session strings.

## Deploy

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/rahgir-Thepathfinder/session)

Click the button above, fill in `API_ID`, `API_HASH`, and `BOT_TOKEN` in
the form Heroku shows you, then deploy. The app runs on a **worker**
dyno (polling), not a web dyno — `app.json` already scales `worker=1`
for you.

## Env vars

| Var | Where to get it |
|---|---|
| `API_ID` | https://my.telegram.org → API Development Tools |
| `API_HASH` | https://my.telegram.org → API Development Tools |
| `BOT_TOKEN` | https://t.me/BotFather |

## Usage

1. Open your bot in Telegram, send `/start`
2. Pick **Pyrogram** or **Telethon**
3. Enter your own `API_ID`, `API_HASH`, phone number, OTP code (and
   2FA password if enabled)
4. Bot replies with your session string

⚠️ A session string grants full account access — never share it.
