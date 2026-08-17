# Robberg Fountain Shack monitor

Checks CapeNature Robberg for one-night availability from **5–15 December 2026** (last arrival 14 December) and sends a Telegram alert when a newly available night appears.

## Setup

1. Create a **public GitHub repository**.
2. Upload these files/folders.
3. Create a Telegram bot with `@BotFather` using `/newbot` and copy its token.
4. Send `/start` to the bot.
5. Find your chat ID with `https://api.telegram.org/botYOUR_TOKEN/getUpdates` and copy the value of `chat.id`.
6. GitHub repo → Settings → Secrets and variables → Actions → New repository secret:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
7. Go to Actions → Robberg Fountain Shack monitor → Run workflow for an immediate test.

It then runs **8 times daily**. It does not book automatically; you get the alert and book yourself.

Booking page: https://booking.capenature.co.za/booking/Robberg

GitHub Actions scheduled jobs can occasionally be delayed. If CapeNature changes its booking-page HTML, the selector logic may need updating; errors will appear in the Actions log.
