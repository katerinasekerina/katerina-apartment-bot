import asyncio
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


STATE_PATH = Path(__file__).resolve().parent / "state.json"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

SOURCES = [
    {
        "key": "myhome_rent",
        "site": "MyHome.ge",
        "deal": "rent",
        "rooms": {1, 2},
        "pages": 5,
        "url": (
            "https://www.myhome.ge/en/real-estate/rent/apartment/tbilisi/vake/1-room/"
            "?deal_types=2&real_estate_types=1&cities=1&urbans=38,47&districts=4"
            "&currency_id=1&CardView=1&owner_type=physical&room_types=1,2&page=1"
        ),
    },
    {
        "key": "myhome_sale",
        "site": "MyHome.ge",
        "deal": "sale",
        "rooms": {1, 2, 3},
        "pages": 5,
        "url": (
            "https://www.myhome.ge/en/real-estate/sale/apartment/tbilisi/vake/1-room/"
            "?deal_types=1&real_estate_types=1&cities=1&urbans=38,47&districts=4"
            "&currency_id=1&CardView=1&owner_type=physical&room_types=1,2,3&page=1"
        ),
    },
    {
        "key": "ss_rent",
        "site": "SS.ge",
        "deal": "rent",
        "rooms": {1, 2},
        "pages": 10,
        "url": (
            "https://home.ss.ge/en/real-estate/l/Flat/For-Rent?cityIdList=95"
            "&subdistrictIds=3%2C47&currencyId=1"
            "&advancedSearch=%7B%22individualEntityOnly%22%3Atrue%7D"
        ),
    },
    {
        "key": "ss_sale",
        "site": "SS.ge",
        "deal": "sale",
        "rooms": {1, 2, 3},
        "pages": 10,
        "url": (
            "https://home.ss.ge/en/real-estate/l/Flat/For-Sale?cityIdList=95"
            "&subdistrictIds=3%2C47&currencyId=1"
            "&advancedSearch=%7B%22individualEntityOnly%22%3Atrue%7D"
        ),
    },
]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_room_count(text: str, url: str) -> int | None:
    combined = f"{text} {url}"
    for pattern in (
        r"(?<!\d)(\d+)\s*[- ]?room\b",
        r"(?<!\d)(\d+)\s*ოთახ",
        r"(?<!\d)(\d+)\s*комнат",
    ):
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def extract_price(text: str) -> str:
    match = re.search(r"(?<!\d)(\d[\d ,.]*?)\s*(₾|\$|€)", text)
    return normalize_text("".join(match.groups())) if match else "—"


def extract_area(text: str) -> str:
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:m²|m2|მ²)",
        text,
        re.IGNORECASE,
    )
    return f"{match.group(1)} m²" if match else "—"


def is_target_location(text: str, url: str) -> bool:
    combined = f"{text} {url}".lower()
    return any(
        name in combined
        for name in (
            "vake",
            "ვაკე",
            "ваке",
            "saburtalo",
            "საბურთალო",
            "сабуртало",
        )
    )


def extract_location(text: str) -> str:
    lowered = text.lower()
    locations = []

    if "vake" in lowered or "ვაკე" in lowered or "ваке" in lowered:
        locations.append("Ваке")

    if (
        "saburtalo" in lowered
        or "საბურთალო" in lowered
        or "сабуртало" in lowered
    ):
        locations.append("Сабуртало")

    return " / ".join(locations) if locations else "Ваке / Сабуртало"


def listing_id_from_url(site: str, url: str) -> str | None:
    if site == "MyHome.ge":
        match = re.search(r"/real-estate/(\d+)(?:/|$)", url)
    else:
        match = re.search(
            r"/real-estate/(?!l/)[^?#]*-(\d+)(?:[/?#]|$)",
            url,
        )

    return match.group(1) if match else None


def page_url(url: str, page_number: int) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(
        parts.query,
        keep_blank_values=True,
    )
    query = [
        (key, value)
        for key, value in query
        if key != "page"
    ]
    query.append(("page", str(page_number)))

    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urllib.parse.urlencode(query),
            parts.fragment,
        )
    )


async def collect_page_links(page: Any) -> list[dict[str, str]]:
    return await page.evaluate(
        r"""
        () => {
          const clean = (value) =>
            (value || '').replace(/\s+/g, ' ').trim();

          const results = [];

          for (const anchor of document.querySelectorAll('a[href]')) {
            const href = anchor.href;

            let text = clean(
              anchor.innerText ||
              anchor.getAttribute('aria-label') ||
              anchor.title
            );

            let node = anchor;

            for (
              let i = 0;
              i < 6 && node && node.parentElement;
              i++
            ) {
              node = node.parentElement;

              const candidate = clean(node.innerText);
              const hasMarker =
                /m²|m2|room|ოთახ|комнат/i.test(candidate);

              if (
                hasMarker &&
                candidate.length >= 25 &&
                candidate.length <= 1200
              ) {
                text = candidate;
                break;
              }
            }

            results.push({href, text});
          }

          return results;
        }
        """
    )


async def scrape_all_sources():
    found: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[str] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            locale="en-US",
            viewport={
                "width": 1440,
                "height": 1200,
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
        )

        await context.add_init_script(
            "Object.defineProperty("
            "navigator, 'webdriver', "
            "{get: () => undefined})"
        )

        for source in SOURCES:
            page_count = int(source.get("pages", 1))

            for page_number in range(1, page_count + 1):
                page = await context.new_page()

                try:
                    print(
                        f"Checking {source['key']} "
                        f"page {page_number}"
                    )

                    await page.goto(
                        page_url(
                            source["url"],
                            page_number,
                        ),
                        wait_until="domcontentloaded",
                        timeout=90_000,
                    )

                    await page.wait_for_timeout(5_000)

                    for _ in range(3):
                        await page.mouse.wheel(0, 1600)
                        await page.wait_for_timeout(700)

                    candidates = await collect_page_links(page)

                    for candidate in candidates:
                        url = candidate["href"].split("#", 1)[0]

                        listing_id = listing_id_from_url(
                            source["site"],
                            url,
                        )

                        if not listing_id:
                            continue

                        text = normalize_text(candidate["text"])

                        if not is_target_location(text, url):
                            continue

                        rooms = extract_room_count(text, url)

                        if (
                            rooms is None
                            or rooms not in source["rooms"]
                        ):
                            continue

                        key = (
                            source["key"],
                            listing_id,
                        )

                        current = found.get(key)

                        if (
                            current
                            and len(current["summary"]) >= len(text)
                        ):
                            continue

                        found[key] = {
                            "source_key": source["key"],
                            "site": source["site"],
                            "deal": source["deal"],
                            "listing_id": listing_id,
                            "url": url,
                            "rooms": rooms,
                            "price": extract_price(text),
                            "area": extract_area(text),
                            "location": extract_location(text),
                            "summary": text[:700],
                        }

                except PlaywrightTimeoutError:
                    errors.append(
                        f"{source['key']} "
                        f"page {page_number}: timeout"
                    )

                except Exception as exc:
                    errors.append(
                        f"{source['key']} "
                        f"page {page_number}: "
                        f"{type(exc).__name__}: {exc}"
                    )

                finally:
                    await page.close()

        await context.close()
        await browser.close()

    return list(found.values()), errors


def default_state() -> dict[str, Any]:
    return {
        "initialized": False,
        "seen": {
            source["key"]: []
            for source in SOURCES
        },
        "max_ids": {
            source["key"]: 0
            for source in SOURCES
        },
        "heartbeat_week": "",
    }


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return default_state()

    try:
        state = json.loads(
            STATE_PATH.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return default_state()

    template = default_state()

    for key, value in template.items():
        state.setdefault(key, value)

    for source in SOURCES:
        state["seen"].setdefault(
            source["key"],
            [],
        )
        state["max_ids"].setdefault(
            source["key"],
            0,
        )

    return state


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def send_telegram(text: str) -> None:
    data = urllib.parse.urlencode(
        {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=data,
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        if response.status != 200:
            raise RuntimeError(
                f"Telegram returned HTTP {response.status}"
            )


def format_listing(item: dict[str, Any]) -> str:
    deal = (
        "Аренда"
        if item["deal"] == "rent"
        else "Продажа"
    )

    safe_url = html.escape(
        item["url"],
        quote=True,
    )

    return (
        "🏠 <b>НОВОЕ ОБЪЯВЛЕНИЕ</b>\n\n"
        f"🌐 <b>Сайт:</b> "
        f"{html.escape(item['site'])}\n"
        f"🔑 <b>Тип:</b> {deal}\n"
        f"📍 <b>Район:</b> "
        f"{html.escape(item['location'])}\n"
        f"🚪 <b>Комнат:</b> {item['rooms']}\n"
        f"📐 <b>Площадь:</b> "
        f"{html.escape(item['area'])}\n"
        f"💰 <b>Цена:</b> "
        f"{html.escape(item['price'])}\n\n"
        f"🔗 <a href=\"{safe_url}\">"
        f"Открыть объявление</a>"
    )


async def main() -> int:
    if not TOKEN or not CHAT_ID:
        print(
            "Missing TELEGRAM_BOT_TOKEN "
            "or TELEGRAM_CHAT_ID",
            file=sys.stderr,
        )
        return 2

    state = load_state()
    listings, errors = await scrape_all_sources()

    if errors:
        print("Errors:")

        for error in errors:
            print(f"- {error}")

    if not listings and errors:
        return 1

    new_items: list[dict[str, Any]] = []
    initialized = bool(state["initialized"])

    for item in listings:
        key = item["source_key"]
        listing_id = item["listing_id"]
        seen = state["seen"][key]

        if listing_id not in seen:
            if (
                initialized
                and int(listing_id)
                > int(state["max_ids"][key])
            ):
                new_items.append(item)

            seen.append(listing_id)
            state["seen"][key] = seen[-500:]

        state["max_ids"][key] = max(
            int(state["max_ids"][key]),
            int(listing_id),
        )

    if not initialized:
        state["initialized"] = True

        send_telegram(
            "✅ Облачный мониторинг включён. "
            "Существующие объявления сохранены; "
            "дальше уведомления будут приходить "
            "только о новых объявлениях."
        )

    else:
        new_items.sort(
            key=lambda item: int(item["listing_id"])
        )

        for item in new_items:
            send_telegram(format_listing(item))

    state["heartbeat_week"] = datetime.now(
        timezone.utc
    ).strftime("%G-W%V")

    save_state(state)

    print(
        f"Found {len(listings)} listings; "
        f"sent {len(new_items)} notifications"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
