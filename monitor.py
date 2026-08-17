import asyncio
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

BOOKING_URL = "https://booking.capenature.co.za/booking/Robberg"

START = date(2026, 12, 5)
END = date(2026, 12, 15)

STATE_FILE = Path("state.json")
TIMEOUT = 45_000


def date_pairs():
    d = START
    while d < END:
        yield d, d + timedelta(days=1)
        d += timedelta(days=1)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass

    return {
        "available": [],
        "last_checked": None
    }


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2)
    )


async def choose_flatpickr_date(page, input_locator, target_date):
    """
    Click a CapeNature Flatpickr date field and select target_date.
    """

    await input_locator.click()

    calendar = page.locator(".flatpickr-calendar").filter(
        has=page.locator(".flatpickr-month")
    ).last

    await calendar.wait_for(
        state="visible",
        timeout=10000
    )

    # Move calendar to the required month.
    for _ in range(24):

        month_text = await calendar.locator(
            ".flatpickr-current-month"
        ).inner_text()

        month_match = re.search(
            r"([A-Za-z]+)\s+(\d{4})",
            month_text
        )

        if not month_match:
            raise RuntimeError(
                f"Could not determine calendar month: {month_text}"
            )

        current_month = month_match.group(1)
        current_year = int(month_match.group(2))

        current = date(
            current_year,
            date(
                target_date.year,
                target_date.month,
                1
            ).month,
            1
        )

        # Instead of relying on month arithmetic from the text,
        # inspect the visible year/month controls.
        month_select = calendar.locator(
            ".flatpickr-monthDropdown-months"
        )

        if await month_select.count():
            selected_month = await month_select.input_value()
            current_year_value = await calendar.locator(
                ".cur-year"
            ).input_value()

            if (
                int(current_year_value) == target_date.year
                and int(selected_month) == target_date.month - 1
            ):
                break

            await month_select.select_option(
                str(target_date.month - 1)
            )

            year_input = calendar.locator(".cur-year")
            await year_input.fill(str(target_date.year))
            await year_input.press("Enter")

            await page.wait_for_timeout(200)

            break

        # Fallback for calendars without month dropdown.
        current_month_num = date(
            target_date.year,
            1,
            1
        ).month

        # Use the calendar's next/previous controls.
        displayed = await calendar.locator(
            ".flatpickr-current-month"
        ).inner_text()

        displayed_match = re.search(
            r"([A-Za-z]+)\s+(\d{4})",
            displayed
        )

        if not displayed_match:
            raise RuntimeError("Unable to read calendar date")

        displayed_month = displayed_match.group(1)
        displayed_year = int(displayed_match.group(2))

        from datetime import datetime

        displayed_month_num = datetime.strptime(
            displayed_month,
            "%B"
        ).month

        diff = (
            target_date.year * 12
            + target_date.month
            - displayed_year * 12
            - displayed_month_num
        )

        if diff > 0:
            for _ in range(diff):
                await calendar.locator(
                    ".flatpickr-next-month"
                ).click()
                await page.wait_for_timeout(50)

        elif diff < 0:
            for _ in range(abs(diff)):
                await calendar.locator(
                    ".flatpickr-prev-month"
                ).click()
                await page.wait_for_timeout(50)

        break

    # Select the correct day.
    day = calendar.locator(
        ".flatpickr-day"
    ).filter(
        has_text=str(target_date.day)
    )

    count = await day.count()

    if count == 0:
        raise RuntimeError(
            f"Could not find day {target_date.day} "
            f"for {target_date}"
        )

    # Flatpickr can contain days from adjacent months.
    for i in range(count):
        candidate = day.nth(i)

        classes = await candidate.get_attribute("class") or ""

        if "prevMonthDay" in classes:
            continue

        if "nextMonthDay" in classes:
            continue

        if "disabled" in classes:
            raise RuntimeError(
                f"Date {target_date} is disabled"
            )

        await candidate.click()
        await page.wait_for_timeout(250)
        return

    raise RuntimeError(
        f"Could not select {target_date}"
    )


async def check_pair(page, arrival, departure):

    await page.goto(
        BOOKING_URL,
        wait_until="domcontentloaded",
        timeout=TIMEOUT
    )

    await page.wait_for_timeout(1000)

    # The first Arrival/Departure pair belongs to accommodation.
    arrival_input = page.locator(
        "#startDate_0"
    )

    departure_input = page.locator(
        "#endDate_0"
    )

    if await arrival_input.count() == 0:
        raise RuntimeError(
            "Could not find accommodation arrival field"
        )

    if await departure_input.count() == 0:
        raise RuntimeError(
            "Could not find accommodation departure field"
        )

    # Select arrival date.
    await choose_flatpickr_date(
        page,
        arrival_input,
        arrival
    )

    # Select departure date.
    await choose_flatpickr_date(
        page,
        departure_input,
        departure
    )

    # Click the first Search button.
    search_button = page.get_by_role(
        "button",
        name=re.compile(
            r"search",
            re.IGNORECASE
        )
    ).first

    await search_button.click()

    await page.wait_for_timeout(2000)

    text = await page.locator(
        "body"
    ).inner_text()

    lower = text.lower()

    # We only care about Fountain Shack.
    if "fountain shack" not in lower:
        return False, text

    start = lower.find("fountain shack")

    section = lower[
        start:start + 3000
    ]

    unavailable_phrases = [
        "no available units",
        "no availability",
        "fully booked",
        "sold out",
        "not available"
    ]

    if any(
        phrase in section
        for phrase in unavailable_phrases
    ):
        return False, section

    positive_phrases = [
        "book now",
        "available",
        "add to basket",
        "select",
        "units available"
    ]

    available = any(
        phrase in section
        for phrase in positive_phrases
    )

    return available, section


async def send_telegram(message):

    token = os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.environ.get(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat_id:
        print(
            "Telegram credentials not configured."
        )
        return False

    import urllib.request
    import urllib.parse

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": False
    }).encode()

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            print(
                "Telegram response:",
                response.read().decode()
            )

            return response.status == 200

    except Exception as e:

        print(
            f"Telegram notification failed: {e}",
            file=sys.stderr
        )

        return False


async def main():

    state = load_state()

    found = []

    async with async_playwright() as playwright:

        browser = await playwright.chromium.launch(
            headless=True
        )

        page = await browser.new_page(
            viewport={
                "width": 1440,
                "height": 1200
            },
            locale="en-GB"
        )

        for arrival, departure in date_pairs():

            try:

                available, details = await check_pair(
                    page,
                    arrival,
                    departure
                )

                print(
                    f"{arrival} -> {departure}: "
                    f"{'AVAILABLE' if available else 'NO AVAILABILITY'}"
                )

                if available:

                    found.append({
                        "arrival": arrival.isoformat(),
                        "departure": departure.isoformat()
                    })

            except Exception as error:

                print(
                    f"{arrival} -> {departure}: ERROR: {error}",
                    file=sys.stderr
                )

        await browser.close()

    old_dates = {
        item["arrival"]
        for item in state.get(
            "available",
            []
        )
    }

    new = [
        item
        for item in found
        if item["arrival"] not in old_dates
    ]

    state["available"] = found

    state["last_checked"] = (
        date.today().isoformat()
    )

    save_state(state)

    # Send Telegram notification for new availability.
    if new:

        lines = [
            "🚨 ROBBERG FOUNTAIN SHACK AVAILABLE!",
            "",
        ]

        for item in new:

            lines.append(
                f"• {item['arrival']} → "
                f"{item['departure']}"
            )

        lines.extend([
            "",
            "Book immediately:",
            BOOKING_URL
        ])

        message = "\n".join(lines)

        print(message)

        await send_telegram(message)

    else:

        print(
            "No new availability found."
        )

    print(
        json.dumps(
            {
                "available": found,
                "new": new
            },
            indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(send_telegram("🧪 Robberg monitor test — Telegram is working!"))
