import asyncio
import json
import os
import re
import urllib.request
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

BOOKING_URL = "https://booking.capenature.co.za/booking/Robberg"

START = date(2026, 12, 5)
END = date(2026, 12, 15)

STATE_FILE = Path("state.json")
TIMEOUT = 45000


def date_pairs():
    current = START

    while current < END:
        yield current, current + timedelta(days=1)
        current += timedelta(days=1)


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


async def choose_date(page, input_selector, target_date):

    await page.locator(input_selector).click()

    calendar = page.locator(
        ".flatpickr-calendar"
    ).filter(
        has=page.locator(".flatpickr-month")
    ).last

    await calendar.wait_for(
        state="visible",
        timeout=10000
    )

    month_dropdown = calendar.locator(
        ".flatpickr-monthDropdown-months"
    )

    year_input = calendar.locator(
        ".cur-year"
    )

    if await month_dropdown.count():

        await month_dropdown.select_option(
            str(target_date.month - 1)
        )

        await year_input.fill(
            str(target_date.year)
        )

        await year_input.press("Enter")

        await page.wait_for_timeout(300)

    else:

        for _ in range(24):

            month_text = await calendar.locator(
                ".flatpickr-current-month"
            ).inner_text()

            match = re.search(
                r"([A-Za-z]+)\s+(\d{4})",
                month_text
            )

            if not match:
                break

            month_name = match.group(1)
            year = int(match.group(2))

            from datetime import datetime

            month = datetime.strptime(
                month_name,
                "%B"
            ).month

            difference = (
                target_date.year * 12
                + target_date.month
                - year * 12
                - month
            )

            if difference == 0:
                break

            if difference > 0:
                await calendar.locator(
                    ".flatpickr-next-month"
                ).click()
            else:
                await calendar.locator(
                    ".flatpickr-prev-month"
                ).click()

            await page.wait_for_timeout(100)

    days = calendar.locator(
        ".flatpickr-day"
    )

    for i in range(await days.count()):

        day = days.nth(i)

        classes = await day.get_attribute(
            "class"
        ) or ""

        if "prevMonthDay" in classes:
            continue

        if "nextMonthDay" in classes:
            continue

        text = (await day.inner_text()).strip()

        if text == str(target_date.day):

            if "disabled" in classes:
                raise RuntimeError(
                    f"{target_date} is disabled"
                )

            await day.click()

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

    await choose_date(
        page,
        "#startDate_0",
        arrival
    )

    await choose_date(
        page,
        "#endDate_0",
        departure
    )

    search = page.get_by_role(
        "button",
        name=re.compile(
            r"search",
            re.I
        )
    ).first

    await search.click()

    await page.wait_for_timeout(2000)

    text = await page.locator(
        "body"
    ).inner_text()

    lower = text.lower()

    if "fountain shack" not in lower:
        return False

    start = lower.find(
        "fountain shack"
    )

    section = lower[
        start:start + 3000
    ]

    unavailable = [
        "no available units",
        "no availability",
        "fully booked",
        "sold out",
        "not available"
    ]

    if any(
        phrase in section
        for phrase in unavailable
    ):
        return False

    positive = [
        "book now",
        "available",
        "add to basket",
        "select",
        "units available"
    ]

    return any(
        phrase in section
        for phrase in positive
    )


def create_github_issue(available):

    token = os.environ.get(
        "GITHUB_TOKEN"
    )

    repository = os.environ.get(
        "GITHUB_REPOSITORY"
    )

    if not token or not repository:
        print(
            "GitHub token/repository not available."
        )
        return

    dates = "\n".join(
        f"- **{x['arrival']} → {x['departure']}**"
        for x in available
    )

    body = f"""
# 🚨 Robberg Fountain Shack available

The monitor found availability for:

{dates}

### Book immediately

{BOOKING_URL}

This alert was generated automatically by the Robberg availability monitor.
"""

    data = json.dumps({
        "title": "🚨 Robberg Fountain Shack available!",
        "body": body,
        "labels": ["availability"]
    }).encode()

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/issues",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            print(
                "GitHub notification created:"
            )

            print(
                response.read().decode()
            )

    except Exception as error:

        print(
            f"GitHub notification failed: {error}"
        )


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

                available = await check_pair(
                    page,
                    arrival,
                    departure
                )

                status = (
                    "AVAILABLE"
                    if available
                    else "NO AVAILABILITY"
                )

                print(
                    f"{arrival} -> {departure}: {status}"
                )

                if available:

                    found.append({
                        "arrival": arrival.isoformat(),
                        "departure": departure.isoformat()
                    })

            except Exception as error:

                print(
                    f"{arrival} -> {departure}: ERROR: {error}"
                )

        await browser.close()

    old = {
        item["arrival"]
        for item in state.get(
            "available",
            []
        )
    }

    new = [
        item
        for item in found
        if item["arrival"] not in old
    ]

    state["available"] = found

    state["last_checked"] = date.today().isoformat()

    save_state(state)

    if new:

        print(
            "NEW AVAILABILITY FOUND!"
        )

        create_github_issue(new)

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
    asyncio.run(main())
