import asyncio
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


STATE_PATH = Path(__file__).resolve().parent / "state.json"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
MANUAL_DISTRICT = os.getenv("MANUAL_DISTRICT", "").strip().lower()
MANUAL_LIMIT = max(1, min(30, int(os.getenv("MANUAL_LIMIT", "30"))))

DISTRICTS = {
    "gldani": {
        "label_ru": "Глдани",
        "myhome_slug": "gldani",
        "ss_subdistrict_id": 33,
        "aliases": ("gldani", "გლდანი", "глдани"),
    },
    "didi_digomi": {
        "label_ru": "Диди Дигоми",
        "myhome_slug": "didi-dighomi",
        "ss_subdistrict_id": 45,
        "aliases": ("didi digomi", "დიდი დიღომი", "диди дигоми"),
    },
    "digomi": {
        "label_ru": "Дигоми",
        "myhome_slug": "dighmis-masivi",
        "ss_subdistrict_id": 28,
        "aliases": (
            "digomi",
            "dighmis masivi",
            "დიღომი",
            "დიღმის მასივი",
            "дигоми",
        ),
    },
    "nadzaladevi": {
        "label_ru": "Надзаладеви",
        "myhome_slug": "nadzaladevi",
        "ss_subdistrict_id": 41,
        "aliases": ("nadzaladevi", "ნაძალადევი", "надзаладеви"),
    },
    "isani": {
        "label_ru": "Исани",
        "myhome_slug": "isani",
        "ss_subdistrict_id": 10,
        "aliases": ("isani", "ისანი", "исани"),
    },
    "bagebi": {
        "label_ru": "Багеби",
        "myhome_slug": "bagebi",
        "ss_subdistrict_id": 44,
        "aliases": ("bagebi", "ბაგები", "багеби"),
    },
}

SOURCES = [
    {
        "key": "myhome_rent",
        "site": "MyHome.ge",
        "deal": "rent",
        "rooms": {1, 2, 3},
        "pages": 10,
        "url": (
            "https://www.myhome.ge/en/real-estate/rent/apartment/tbilisi/vake/1-room/"
            "?deal_types=2&real_estate_types=1&cities=1&urbans=38,47&districts=4"
            "&currency_id=1&CardView=1&owner_type=physical&room_types=1,2,3&page=1"
        ),
    },
    {
        "key": "ss_rent",
        "site": "SS.ge",
        "deal": "rent",
        "rooms": {1, 2, 3},
        "pages": 10,
        "url": (
            "https://home.ss.ge/en/real-estate/l/Flat/For-Rent?cityIdList=95"
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


def extract_price(text: str, usd_rate: float) -> str:
    match = re.search(r"(?<!\d)(\d[\d ,.]*?)\s*(₾|\$|€)", text)

    if not match:
        return "—"

    amount_text, currency = match.groups()
    compact = re.sub(r"[\s,]", "", amount_text)

    try:
        amount = float(compact)
    except ValueError:
        return "—"

    if currency == "₾":
        amount /= usd_rate
    elif currency == "€":
        return "—"

    rounded = int(round(amount))
    return f"{rounded:,} $"


def get_usd_rate() -> float:
    """Get USD/GEL rate without letting a temporary NBG/DNS outage stop the run."""
    url = (
        "https://nbg.gov.ge/gw/api/ct/monetarypolicy/"
        "currencies/en/json/?currencies=USD"
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    last_error: Exception | None = None

    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.load(response)

            for day in payload:
                for currency in day.get("currencies", []):
                    if currency.get("code") == "USD":
                        rate = float(currency["rate"])
                        if rate > 0:
                            return rate

            raise RuntimeError("USD rate was not returned by NBG")

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as error:
            last_error = error
            print(
                f"NBG USD rate attempt {attempt}/3 failed: {error}",
                file=sys.stderr,
            )
            if attempt < 3:
                time.sleep(2 * attempt)

    fallback_rate = 2.70
    print(
        "WARNING: NBG USD rate unavailable after 3 attempts; "
        f"using temporary fallback {fallback_rate:.2f} GEL/USD. "
        f"Last error: {last_error}",
        file=sys.stderr,
    )
    return fallback_rate


def extract_area(text: str) -> str:
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:m²|m2|მ²)",
        text,
        re.IGNORECASE,
    )
    return f"{match.group(1)} m²" if match else "—"


def is_target_location(
    text: str,
    url: str,
    source: dict[str, Any] | None = None,
) -> bool:
    combined = urllib.parse.unquote(f"{text} {url}").lower()

    if source and source.get("district_aliases"):
        return any(
            str(name).lower() in combined
            for name in source["district_aliases"]
        )

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


def extract_location(
    text: str,
    source: dict[str, Any] | None = None,
) -> str:
    if source and source.get("district_label"):
        return str(source["district_label"])

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


def manual_sources_for_district(
    district_key: str,
) -> list[dict[str, Any]]:
    config = DISTRICTS[district_key]
    myhome_query = urllib.parse.urlencode(
        {
            "deal_types": "2",
            "real_estate_types": "1",
            "cities": "1",
            "currency_id": "1",
            "CardView": "1",
            "owner_type": "physical",
            "room_types": "1,2,3",
            "page": "1",
        }
    )
    ss_query = urllib.parse.urlencode(
        {
            "cityIdList": "95",
            "subdistrictIds": str(config["ss_subdistrict_id"]),
            "currencyId": "1",
            "advancedSearch": json.dumps(
                {"individualEntityOnly": True},
                separators=(",", ":"),
            ),
        }
    )
    shared = {
        "deal": "rent",
        "rooms": {1, 2, 3},
        "pages": 3,
        "district_aliases": config["aliases"],
        "district_label": config["label_ru"],
        "manual_search": True,
    }

    return [
        {
            **shared,
            "key": f"manual_myhome_{district_key}",
            "site": "MyHome.ge",
            "url": (
                "https://www.myhome.ge/en/real-estate/rent/apartment/"
                f"tbilisi/{config['myhome_slug']}/?{myhome_query}"
            ),
        },
        {
            **shared,
            "key": f"manual_ss_{district_key}",
            "site": "SS.ge",
            "url": (
                "https://home.ss.ge/en/real-estate/l/Flat/For-Rent?"
                f"{ss_query}"
            ),
        },
    ]


def extract_address(text: str, location: str) -> str:
    patterns = (
        r"((?:[A-Za-zА-Яа-яЁёႠ-ჿ0-9][A-Za-zА-Яа-яЁёႠ-ჿ0-9.'’()/-]*\s+)"
        r"{1,7}(?:st|street|ave|avenue|road|rd|highway)\.?)"
        r"(?![A-Za-z])",
        r"((?:[A-Za-zА-Яа-яЁёႠ-ჿ0-9][A-Za-zА-Яа-яЁёႠ-ჿ0-9.'’()/-]*\s+)"
        r"{1,7}(?:ქ\.|ქუჩა|გამზირი|ჩიხი|გზატკეცილი))"
        r"(?![Ⴀ-ჿ])",
        r"((?:ул(?:ица)?|проспект|пр-т)\.?\s+"
        r"[A-Za-zА-Яа-яЁёႠ-ჿ][A-Za-zА-Яа-яЁёႠ-ჿ.'’()/-]*"
        r"(?:\s+[A-Za-zА-Яа-яЁёႠ-ჿ][A-Za-zА-Яа-яЁёႠ-ჿ.'’()/-]*){0,5})",
    )

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            address = normalize_text(match.group(1))
            tail = text[match.end():]
            number_match = re.match(
                r"\s*(?:№|No\.?)?\s*([0-9][A-Za-z0-9/-]*)",
                tail,
                re.IGNORECASE,
            )

            if number_match:
                after_number = tail[number_match.end():]

                if not re.match(r"\s*m[²2]", after_number, re.IGNORECASE):
                    address = f"{address} {number_match.group(1)}"

            address = re.sub(
                r"^.*(?:Vake|Saburtalo|Ваке|Сабуртало|ვაკე|საბურთალო)\s+",
                "",
                address,
                flags=re.IGNORECASE,
            )
            address = re.sub(
                r"^\d[\d ,.]*\s*(?:₾|\$|€)\s*",
                "",
                address,
            )
            address = normalize_text(address).strip(" -|,.;")

            if re.search(
                r"real estate|publish|log in|login|advertisement|"
                r"разместить|авторизац|реклама|განცხადების დამატება",
                address,
                re.IGNORECASE,
            ):
                continue

            if 2 <= len(address) <= 100 and len(address.split()) <= 9:
                return address

    return location


def listing_id_from_url(site: str, url: str) -> str | None:
    """Extract a listing ID from both legacy and current MyHome URL formats."""
    if site != "MyHome.ge":
        match = re.search(
            r"/real-estate/(?!l/)[^?#]*-(\d+)(?:[/?#]|$)",
            url,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    try:
        parts = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(parts.path)
    except Exception:
        path = urllib.parse.unquote(url)

    # Only treat URLs under known MyHome listing roots as listing candidates.
    if not re.search(r"/(?:udzravi-qoneba|real-estate)(?:/|$)", path, re.IGNORECASE):
        return None

    patterns = (
        r"/(?:udzravi-qoneba|real-estate)/(\d{6,10})(?:/|$)",
        r"/(?:udzravi-qoneba|real-estate)/[^/?#]*-(\d{6,10})(?:/|$)",
        r"-(\d{6,10})(?:/)?$",
        r"/(\d{6,10})(?:/)?$",
    )

    for regex in patterns:
        match = re.search(regex, path, re.IGNORECASE)
        if match:
            return match.group(1)

    try:
        query = urllib.parse.parse_qs(parts.query)
    except Exception:
        query = {}

    for key in ("id", "listing_id", "statement_id", "pr_id"):
        values = query.get(key, [])
        for value in values:
            if re.fullmatch(r"\d{6,10}", value or ""):
                return value

    return None

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
            let card = anchor;

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
                card = node;
                break;
              }
            }

            const imageNode =
              card.querySelector('img') ||
              anchor.querySelector('img');

            let image = '';

            if (imageNode) {
              image = [
                imageNode.currentSrc ||
                '',
                imageNode.src ||
                '',
                imageNode.getAttribute('data-src') ||
                '',
                imageNode.getAttribute('data-lazy-src') ||
                '',
                imageNode.getAttribute('data-original') ||
                ''
              ].find((value) => /^https?:\/\//i.test(value)) || '';
            }

            if (!image) {
              const backgroundNode = Array.from(
                card.querySelectorAll('*')
              ).find((element) => {
                const value = getComputedStyle(element).backgroundImage;
                return value && value !== 'none' && /url\(/i.test(value);
              });

              if (backgroundNode) {
                const value = getComputedStyle(
                  backgroundNode
                ).backgroundImage;
                const match = value.match(/url\(["']?(.*?)["']?\)/i);
                image = match ? match[1] : '';
              }
            }

            if (!/^https?:\/\//i.test(image)) {
              image = '';
            }

            results.push({href, text, image});
          }

          return results;
        }
        """
    )


def is_property_photo_url(url: str) -> bool:
    lowered = urllib.parse.unquote(url or "").lower()

    if not lowered.startswith(("http://", "https://")):
        return False

    if re.search(
        r"logo|icon|avatar|profile|owner|flag|badge|banner|advert|"
        r"adline|roaming|promo|campaign|googleplay|appstore|qr|sprite|favicon",
        lowered,
    ):
        return False

    host = urllib.parse.urlsplit(lowered).netloc

    if host.endswith("static.ss.ge"):
        return bool(
            re.search(r"/20\d{6}/", lowered)
            and re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", lowered)
        )

    if host.endswith("static.my.ge"):
        return bool(
            re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", lowered)
        )

    return False


async def screenshot_image_url(context: Any, image_url: str) -> bytes | None:
    if not is_property_photo_url(image_url):
        return None

    image_page = await context.new_page()

    try:
        await image_page.goto(
            image_url,
            wait_until="load",
            timeout=45_000,
        )
        image = image_page.locator("img").first
        await image.wait_for(state="visible", timeout=15_000)
        photo = await image.screenshot(
            type="jpeg",
            quality=86,
            animations="disabled",
            timeout=20_000,
        )

        if 2_000 <= len(photo) <= 9_500_000:
            return photo
    except Exception:
        return None
    finally:
        await image_page.close()

    return None


async def placeholder_photo(context: Any) -> bytes:
    placeholder = await context.new_page()

    try:
        await placeholder.set_viewport_size({"width": 900, "height": 560})
        await placeholder.set_content(
            """
            <style>
              html, body {
                margin: 0;
                width: 900px;
                height: 560px;
                background: #1f2633;
                color: #ffffff;
                font-family: Arial, sans-serif;
              }
              main {
                width: 900px;
                height: 560px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
              }
              .icon { font-size: 110px; }
              .text { margin-top: 25px; font-size: 42px; font-weight: 700; }
              .sub { margin-top: 14px; font-size: 25px; color: #c9d1dc; }
            </style>
            <main>
              <div class="icon">🏠</div>
              <div class="text">ФОТО НЕДОСТУПНО</div>
              <div class="sub">Откройте объявление для просмотра</div>
            </main>
            """,
            wait_until="load",
        )
        return await placeholder.screenshot(
            type="jpeg",
            quality=86,
            full_page=False,
        )
    finally:
        await placeholder.close()


async def capture_listing_photo(
    page: Any,
    preferred_url: str = "",
) -> bytes:
    preferred_photo = await screenshot_image_url(
        page.context,
        preferred_url,
    )

    if preferred_photo:
        return preferred_photo

    image_data = await page.evaluate(
        r"""
        () => {
          const absoluteUrl = (value) => {
            if (!value) return '';

            try {
              return new URL(value, document.baseURI).href;
            } catch (_) {
              return '';
            }
          };

          const blocked = /logo|icon|avatar|profile|owner|flag|badge|banner|advert|adline|roaming|promo|campaign|googleplay|appstore|qr|sprite|favicon/i;
          const candidates = [];

          const addCandidate = (value, index, width, height, hint) => {
            const source = absoluteUrl(value);

            if (!source || blocked.test(`${source} ${hint || ''}`)) {
              return;
            }

            const lowered = source.toLowerCase();
            let score = Math.min((width || 0) * (height || 0), 600000);

            if (/static\.ss\.ge\/20\d{6}\//i.test(lowered)) {
              score += 3000000;
            } else if (/static\.my\.ge/i.test(lowered)) {
              score += 2000000;
            } else {
              return;
            }

            if (/_thumb\.(?:jpe?g|png|webp)/i.test(lowered)) {
              score += 400000;
            }

            if (/photo|image|gallery|swiper/i.test(hint || '')) {
              score += 250000;
            }

            candidates.push({source, index, score});
          };

          Array.from(document.images).forEach((image, index) => {
            const rect = image.getBoundingClientRect();
            const width = Math.max(image.naturalWidth || 0, rect.width || 0);
            const height = Math.max(image.naturalHeight || 0, rect.height || 0);
            const hint = `${image.alt || ''} ${image.className || ''}`;
            const sources = [
              image.currentSrc,
              image.src,
              image.getAttribute('data-src'),
              image.getAttribute('data-lazy-src'),
              image.getAttribute('data-original')
            ];

            const srcset =
              image.getAttribute('srcset') ||
              image.closest('picture')?.querySelector('source')?.srcset ||
              '';

            for (const entry of srcset.split(',')) {
              sources.push(entry.trim().split(/\s+/)[0]);
            }

            for (const source of sources) {
              addCandidate(source, index, width, height, hint);
            }
          });

          for (const selector of [
            'meta[property="og:image"]',
            'meta[name="twitter:image"]'
          ]) {
            const meta = document.querySelector(selector);
            addCandidate(meta?.content || '', null, 0, 0, selector);
          }

          candidates.sort((a, b) => b.score - a.score);
          return candidates[0] || {source: '', index: null, score: 0};
        }
        """
    )

    image_url = str(image_data.get("source") or "").strip()
    selected_photo = await screenshot_image_url(
        page.context,
        image_url,
    )

    if selected_photo:
        return selected_photo

    return await placeholder_photo(page.context)


async def capture_myhome_photo(page: Any, preferred_url: str = "") -> bytes | None:
    """
    MyHome-specific photo capture for automatic monitoring.
    Tries MyHome detail-page meta/gallery image URLs first, using the same
    Playwright browser session and referrer. Falls back to screenshotting the
    largest visible property image element.
    """
    candidates = await page.evaluate(
        r"""
        () => {
          const absolute = (value) => {
            if (!value) return '';
            try { return new URL(value, document.baseURI).href; }
            catch (_) { return ''; }
          };

          const blocked =
            /logo|icon|avatar|profile|owner|flag|badge|banner|advert|promo|campaign|googleplay|appstore|qr|sprite|favicon/i;

          const seen = new Set();
          const out = [];

          const add = (value, score, index = null, hint = '') => {
            const url = absolute(value);
            if (!url || seen.has(url)) return;
            if (!/^https?:\/\//i.test(url)) return;
            if (blocked.test(`${url} ${hint || ''}`)) return;
            seen.add(url);
            out.push({url, score, index});
          };

          for (const selector of [
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
            'meta[property="twitter:image"]'
          ]) {
            const node = document.querySelector(selector);
            if (node?.content) add(node.content, 6000000, null, selector);
          }

          Array.from(document.images).forEach((img, index) => {
            const rect = img.getBoundingClientRect();
            const width = Math.max(img.naturalWidth || 0, rect.width || 0);
            const height = Math.max(img.naturalHeight || 0, rect.height || 0);
            const hint = `${img.alt || ''} ${img.className || ''} ${img.id || ''}`;

            if (width < 250 || height < 160) return;

            let score = Math.min(width * height, 3000000);
            if (/gallery|swiper|photo|image|slider|carousel/i.test(hint)) {
              score += 1500000;
            }

            const urls = [
              img.currentSrc,
              img.src,
              img.getAttribute('data-src'),
              img.getAttribute('data-lazy-src'),
              img.getAttribute('data-original')
            ];

            const srcset = img.getAttribute('srcset') || '';
            for (const part of srcset.split(',')) {
              urls.push((part.trim().split(/\s+/)[0] || ''));
            }

            for (const value of urls) {
              add(value, score, index, hint);
            }
          });

          out.sort((a, b) => b.score - a.score);
          return out.slice(0, 20);
        }
        """
    )

    ordered_urls = []
    if preferred_url:
        ordered_urls.append(str(preferred_url).strip())

    ordered_urls.extend(
        str(item.get("url") or "").strip()
        for item in candidates
        if item.get("url")
    )

    seen_urls = set()

    for image_url in ordered_urls:
        if not image_url or image_url in seen_urls:
            continue
        seen_urls.add(image_url)

        try:
            response = await page.context.request.get(
                image_url,
                headers={
                    "Referer": page.url,
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
                timeout=20_000,
            )

            if not response.ok:
                continue

            content_type = (
                response.headers.get("content-type") or ""
            ).lower()

            if not content_type.startswith("image/"):
                continue

            photo = await response.body()

            if 2_000 <= len(photo) <= 9_500_000:
                print(
                    f"MYHOME_AUTO_PHOTO direct_ok "
                    f"bytes={len(photo)}"
                )
                return photo

        except Exception as exc:
            print(
                f"MYHOME_AUTO_PHOTO direct_fail "
                f"{type(exc).__name__}"
            )

    for item in candidates:
        index = item.get("index")

        if index is None:
            continue

        try:
            locator = page.locator("img").nth(int(index))

            if not await locator.is_visible():
                continue

            box = await locator.bounding_box()

            if (
                not box
                or box["width"] < 250
                or box["height"] < 160
            ):
                continue

            photo = await locator.screenshot(
                type="jpeg",
                quality=88,
                animations="disabled",
                timeout=15_000,
            )

            if 2_000 <= len(photo) <= 9_500_000:
                print(
                    f"MYHOME_AUTO_PHOTO element_ok "
                    f"bytes={len(photo)}"
                )
                return photo

        except Exception:
            continue

    print("MYHOME_AUTO_PHOTO no_real_photo_found")
    return None


WHATSAPP_PREFILL_TEXT = (
    "გამარჯობა. თქვენი ბინის განცხადებასთან დაკავშირებით გწერთ. "
    "მყავს რამდენიმე კლიენტი, ვისთვისაც თქვენი ბინა შესაძლოა საინტერესო იყოს. "
    "მაინტერესებს, თანამშრომლობთ თუ არა სააგენტოებთან და შესაძლებელია თუ არა "
    "ბინის ჩვენება ჩემი კლიენტებისთვის?"
)

def normalize_georgian_mobile(value: str) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("00995"):
        digits = digits[2:]
    local = digits[3:] if digits.startswith("995") else digits
    if len(local) != 9 or not local.startswith("5"):
        return None
    return f"+995{local}"

def whatsapp_link(phone: str) -> str:
    normalized = normalize_georgian_mobile(phone)
    if not normalized:
        return ""
    digits = normalized.lstrip("+")
    text = urllib.parse.quote(WHATSAPP_PREFILL_TEXT, safe="")
    return f"https://wa.me/{digits}?text={text}"

async def extract_listing_phone(page: Any, site: str) -> str | None:
    """
    Extract ONLY the listing owner's/seller's Georgian mobile number.

    Safety rule:
    - Never accept the first mobile number found somewhere on the whole page.
    - First isolate the visible owner/seller contact card.
    - Read/click only inside that card.
    - If the card cannot be identified confidently, return None rather than
      create a WhatsApp button for a potentially unrelated number.
    """

    mobile_pattern = (
        r"(?:\+?995[\s().-]*)?5\d{2}(?:[\s().-]*\d){6}"
    )

    def normalize_candidates(values: list[str]) -> str | None:
        for raw in values:
            decoded = urllib.parse.unquote(str(raw or ""))
            decoded = decoded.replace("\\u002B", "+").replace("\\/", "/")
            for fragment in re.findall(mobile_pattern, decoded):
                phone = normalize_georgian_mobile(fragment)
                if phone:
                    return phone
        return None

    # Site-specific labels. Both sites are searched in English in production,
    # but KA/RU variants are included in case the site changes locale.
    if site == "MyHome.ge":
        marker_source = (
            r"^(?:owner|მეპატრონე|владелец)$"
        )
    elif site == "SS.ge":
        marker_source = (
            r"^(?:owner|private\s+person|individual|seller|"
            r"მეპატრონე|ფიზიკური\s+პირი|"
            r"владелец|частное\s+лицо|продавец)$"
        )
    else:
        return None

    async def mark_best_contact_card(frame: Any) -> bool:
        try:
            return bool(
                await frame.evaluate(
                    r"""
                    ({markerSource}) => {
                      document.querySelectorAll('[data-owner-contact-card="1"]')
                        .forEach((node) => node.removeAttribute('data-owner-contact-card'));

                      const markerRe = new RegExp(markerSource, 'i');
                      const clean = (value) =>
                        String(value || '').replace(/\s+/g, ' ').trim();

                      const phoneRe =
                        /(?:\+?995[\s().-]*)?5\d{2}(?:[\s().-]*\d){6}/;

                      const contactHintRe =
                        /phone|mobile|tel|contact|call|show.?number|whatsapp|ნომრ|ტელეფონ|მობილურ|დარეკ|დაკავშირ|номер|телефон|позвон|связат/i;

                      // MyHome often renders the owner's mobile masked, e.g.
                      // "593 124 ***". That is still a strong contact-card
                      // signal even though it is not yet a complete phone.
                      const maskedPhoneRe =
                        /(?:\+?995[\s().-]*)?5\d{2}(?:[\s().-]*\d){3,5}[\s().-]*\*{2,}/;

                      const markers = Array.from(document.querySelectorAll('*'))
                        .filter((el) => {
                          const own = clean(el.textContent);
                          if (!own || own.length > 60) return false;
                          return markerRe.test(own);
                        });

                      let best = null;

                      for (const marker of markers) {
                        let node = marker;

                        for (let depth = 0; depth < 8 && node; depth++, node = node.parentElement) {
                          const text = clean(node.innerText || node.textContent);
                          if (!text || text.length > 2600) continue;

                          const controls = Array.from(
                            node.querySelectorAll(
                              'a[href],button,[role="button"],' +
                              '[data-phone],[data-mobile],[data-tel],[data-contact],' +
                              '[aria-label],[title]'
                            )
                          );

                          const fingerprint = clean(
                            controls.map((el) => [
                              el.getAttribute('href') || '',
                              el.getAttribute('aria-label') || '',
                              el.getAttribute('title') || '',
                              el.getAttribute('data-phone') || '',
                              el.getAttribute('data-mobile') || '',
                              el.getAttribute('data-tel') || '',
                              el.getAttribute('data-contact') || '',
                              el.innerText || el.textContent || ''
                            ].join(' ')).join(' ')
                          );

                          const combined = `${text} ${fingerprint}`;
                          const hasPhone = phoneRe.test(combined);
                          const hasMaskedPhone = maskedPhoneRe.test(combined);
                          const hasContactControl = contactHintRe.test(fingerprint);

                          if (!hasPhone && !hasMaskedPhone && !hasContactControl) continue;

                          // Prefer the smallest ancestor that contains the
                          // owner label plus a phone/contact control.
                          const score =
                            text.length +
                            depth * 120 -
                            (hasPhone ? 800 : 0) -
                            (hasMaskedPhone ? 600 : 0) -
                            (hasContactControl ? 300 : 0);

                          if (!best || score < best.score) {
                            best = {node, score};
                          }
                        }
                      }

                      if (!best) return false;
                      best.node.setAttribute('data-owner-contact-card', '1');
                      return true;
                    }
                    """,
                    {"markerSource": marker_source},
                )
            )
        except Exception:
            return False

    async def values_from_marked_card(frame: Any) -> list[str]:
        try:
            return await frame.evaluate(
                r"""
                () => {
                  const card =
                    document.querySelector('[data-owner-contact-card="1"]');
                  if (!card) return [];

                  const out = [];
                  const add = (value) => {
                    const text = String(value || '').trim();
                    if (text) out.push(text);
                  };

                  add(card.innerText || card.textContent || '');

                  for (const el of card.querySelectorAll(
                    'a[href],[data-phone],[data-mobile],[data-tel],[data-contact],' +
                    '[aria-label],[title],[value]'
                  )) {
                    add(el.getAttribute('href'));
                    add(el.getAttribute('data-phone'));
                    add(el.getAttribute('data-mobile'));
                    add(el.getAttribute('data-tel'));
                    add(el.getAttribute('data-contact'));
                    add(el.getAttribute('aria-label'));
                    add(el.getAttribute('title'));
                    add(el.getAttribute('value'));
                    add(el.innerText || el.textContent || '');
                  }

                  return out.slice(0, 250);
                }
                """
            )
        except Exception:
            return []

    async def read_marked_card_phone(frame: Any) -> str | None:
        return normalize_candidates(await values_from_marked_card(frame))

    # Mark and inspect contact cards in all frames.
    marked_frames: list[Any] = []
    for frame in page.frames:
        if await mark_best_contact_card(frame):
            marked_frames.append(frame)
            phone = await read_marked_card_phone(frame)
            if phone:
                return phone

    # If the phone is masked, click ONLY controls inside the already-isolated
    # owner/seller card, never arbitrary phone-looking controls on the page.
    for frame in marked_frames:
        try:
            controls = frame.locator(
                '[data-owner-contact-card="1"] '
                'a[href], '
                '[data-owner-contact-card="1"] button, '
                '[data-owner-contact-card="1"] [role="button"], '
                '[data-owner-contact-card="1"] [class*="phone" i], '
                '[data-owner-contact-card="1"] [class*="contact" i], '
                '[data-owner-contact-card="1"] [class*="call" i], '
                '[data-owner-contact-card="1"] [class*="tel" i]'
            )
            count = min(await controls.count(), 40)
        except Exception:
            continue

        for index in range(count):
            control = controls.nth(index)
            try:
                if not await control.is_visible():
                    continue

                fingerprint = await control.evaluate(
                    r"""
                    (el) => [
                      el.innerText || '',
                      el.textContent || '',
                      el.getAttribute('href') || '',
                      el.getAttribute('aria-label') || '',
                      el.getAttribute('title') || '',
                      el.getAttribute('class') || ''
                    ].join(' ').slice(0, 3000)
                    """
                )

                if not re.search(
                    r"phone|mobile|tel|contact|call|show.?number|whatsapp|"
                    r"ნომრ|ტელეფონ|მობილურ|დარეკ|დაკავშირ|"
                    r"номер|телефон|позвон|связат|"
                    r"\*{2,}",
                    fingerprint,
                    re.I,
                ):
                    continue

                try:
                    await control.click(timeout=3_500)
                except Exception:
                    continue

                await page.wait_for_timeout(1_200)

                # Re-mark in case the framework replaced the contact card.
                if await mark_best_contact_card(frame):
                    phone = await read_marked_card_phone(frame)
                    if phone:
                        return phone
            except Exception:
                continue

    # Fail closed: no generic page-wide phone fallback.
    return None


async def enrich_new_listings(items: list[dict[str, Any]]) -> None:
    if not items:
        return

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
            viewport={"width": 1440, "height": 1200},
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

        for item in items:
            page = await context.new_page()

            try:
                await page.goto(
                    item["url"],
                    wait_until="domcontentloaded",
                    timeout=75_000,
                )
                await page.wait_for_timeout(3_000)

                if not item.get("manual_search"):
                    try:
                        item["phone"] = await extract_listing_phone(page, str(item.get("site") or ""))
                        if item.get("phone"):
                            print(f"OWNER_PHONE {item['site']} {item['listing_id']}: {item['phone']}")
                        else:
                            print(f"OWNER_PHONE not_found {item['site']} {item['listing_id']}")
                    except Exception as exc:
                        print(f"OWNER_PHONE failed {item['site']} {item['listing_id']}: {type(exc).__name__}: {exc}")

                if item.get("site") == "MyHome.ge":
                    myhome_photo = await capture_myhome_photo(
                        page,
                        str(item.get("image") or ""),
                    )
                    item["photo_bytes"] = (
                        myhome_photo
                        or await capture_listing_photo(
                            page,
                            str(item.get("image") or ""),
                        )
                    )
                else:
                    item["photo_bytes"] = await capture_listing_photo(
                        page,
                        str(item.get("image") or ""),
                    )

            except Exception as exc:
                print(
                    f"Detail page failed for {item['listing_id']}: "
                    f"{type(exc).__name__}: {exc}"
                )
            finally:
                await page.close()

        await context.close()
        await browser.close()


async def scrape_all_sources(
    sources: list[dict[str, Any]] | None = None,
):
    found: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[str] = []
    usd_rate = get_usd_rate()
    print(f"USD/GEL rate: {usd_rate}")

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

        for source in (sources or SOURCES):
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

                        if not is_target_location(text, url, source):
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
                            if (
                                not current.get("image")
                                and candidate.get("image")
                            ):
                                current["image"] = candidate["image"]
                            continue

                        location = extract_location(text, source)
                        image_url = candidate.get("image", "")

                        if current and not image_url:
                            image_url = current.get("image", "")

                        found[key] = {
                            "source_key": source["key"],
                            "site": source["site"],
                            "deal": source["deal"],
                            "listing_id": listing_id,
                            "url": url,
                            "rooms": rooms,
                            "price": extract_price(text, usd_rate),
                            "area": extract_area(text),
                            "location": location,
                            "address": extract_address(text, location),
                            "image": image_url,
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


def send_telegram(
    text: str,
    reply_markup: str = "",
) -> None:
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    data = urllib.parse.urlencode(payload).encode("utf-8")

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


def listing_reply_markup(item: dict[str, Any]) -> str:
    """Single full-row WhatsApp button for automatic listings only."""
    if item.get("manual_search"):
        return ""

    phone = normalize_georgian_mobile(str(item.get("phone") or ""))
    if not phone:
        return ""

    url = whatsapp_link(phone)
    if not url:
        return ""

    return json.dumps(
        {
            "inline_keyboard": [
                [
                    {
                        "text": "🟢 НАПИСАТЬ В WHATSAPP",
                        "url": url,
                    }
                ]
            ]
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def multipart_body(
    fields: dict[str, str],
    file_field: str,
    file_name: str,
    file_bytes: bytes,
) -> tuple[bytes, str]:
    boundary = f"----ApartmentBot{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{name}"'
                    "\r\n\r\n"
                ).encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                "Content-Disposition: form-data; "
                f'name="{file_field}"; filename="{file_name}"\r\n'
                "Content-Type: image/jpeg\r\n\r\n"
            ).encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )

    return b"".join(chunks), boundary


def send_listing(item: dict[str, Any]) -> None:
    caption = format_listing(item)
    reply_markup = listing_reply_markup(item)
    photo_bytes = item.get("photo_bytes")
    image_url = str(item.get("image") or "").strip()

    if (
        isinstance(photo_bytes, bytes)
        and 2_000 <= len(photo_bytes) <= 9_500_000
    ):
        try:
            fields = {
                "chat_id": CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML",
            }
            if reply_markup:
                fields["reply_markup"] = reply_markup

            data, boundary = multipart_body(
                fields,
                "photo",
                f"listing-{item['listing_id']}.jpg",
                photo_bytes,
            )
            request = urllib.request.Request(
                f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                data=data,
                headers={
                    "Content-Type": (
                        f"multipart/form-data; boundary={boundary}"
                    )
                },
                method="POST",
            )

            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"Telegram returned HTTP {response.status}"
                    )
            return
        except Exception as exc:
            print(
                f"Uploaded photo failed for {item['listing_id']}: "
                f"{type(exc).__name__}: {exc}"
            )

    if not image_url:
        send_telegram(caption, reply_markup)
        return

    payload = {
        "chat_id": CHAT_ID,
        "photo": image_url,
        "caption": caption,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    data = urllib.parse.urlencode(payload).encode("utf-8")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
        data=data,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Telegram returned HTTP {response.status}"
                )
    except Exception as exc:
        print(
            f"Photo delivery failed for {item['listing_id']}: "
            f"{type(exc).__name__}: {exc}; sending text instead"
        )
        send_telegram(caption, reply_markup)


def format_listing(item: dict[str, Any]) -> str:
    safe_url = html.escape(
        item["url"],
        quote=True,
    )
    safe_location = html.escape(item["location"])
    address = normalize_text(str(item.get("address") or ""))
    safe_address = html.escape(address)
    safe_price = html.escape(item["price"])
    address_line = ""

    if address and address.casefold() != item["location"].casefold():
        address_line = f"📌 <b>Адрес:</b> {safe_address}\n"

    title = (
        "🔎 <b>РЕЗУЛЬТАТ ПОИСКА</b>"
        if item.get("manual_search")
        else "🏠 <b>НОВОЕ ОБЪЯВЛЕНИЕ</b>"
    )

    return (
        f"{title}\n\n"
        f"🌐 <b>Сайт:</b> "
        f"{html.escape(item['site'])}\n"
        "🔑 <b>Тип:</b> Аренда\n"
        f"📍 <b>Район:</b> "
        f"{safe_location}\n"
        f"{address_line}"
        f"💰 <b>Цена:</b> {safe_price}\n"
        f"🚪 <b>Комнат:</b> {item['rooms']}\n"
        f"📐 <b>Площадь:</b> "
        f"{html.escape(item['area'])}\n"
        "\n"
        f"🔗 <a href=\"{safe_url}\">"
        f"Открыть объявление</a>"
    )


def select_manual_listings(
    listings: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    by_source: dict[str, list[dict[str, Any]]] = {}

    for item in listings:
        by_source.setdefault(
            str(item["source_key"]),
            [],
        ).append(item)

    for items in by_source.values():
        items.sort(
            key=lambda item: int(item["listing_id"]),
            reverse=True,
        )

    selected: list[dict[str, Any]] = []
    source_keys = list(by_source)
    rank = 0

    while len(selected) < limit:
        added = False

        for key in source_keys:
            items = by_source[key]

            if rank < len(items):
                selected.append(items[rank])
                added = True

                if len(selected) >= limit:
                    break

        if not added:
            break

        rank += 1

    return selected


async def run_manual_search() -> int:
    if MANUAL_DISTRICT not in DISTRICTS:
        print(
            f"Unknown MANUAL_DISTRICT: {MANUAL_DISTRICT}",
            file=sys.stderr,
        )
        return 2

    config = DISTRICTS[MANUAL_DISTRICT]
    district_label = str(config["label_ru"])

    send_telegram(
        f"🔎 Ищу актуальные объявления: <b>{html.escape(district_label)}</b>..."
    )

    listings, errors = await scrape_all_sources(
        manual_sources_for_district(MANUAL_DISTRICT)
    )

    if errors:
        print("Manual search errors:")

        for error in errors:
            print(f"- {error}")

    selected = select_manual_listings(
        listings,
        MANUAL_LIMIT,
    )

    if not selected:
        send_telegram(
            "ℹ️ По выбранному району подходящих объявлений "
            "сейчас не найдено."
        )
        return 1 if errors else 0

    for item in selected:
        item["manual_search"] = True

    await enrich_new_listings(selected)

    for item in selected:
        send_listing(item)

    send_telegram(
        f"✅ Поиск завершён: <b>{html.escape(district_label)}</b>. "
        f"Отправлено объявлений: <b>{len(selected)}</b>."
    )

    print(
        f"Manual search {MANUAL_DISTRICT}: "
        f"found {len(listings)} listings; "
        f"sent {len(selected)} results"
    )

    return 0


async def main() -> int:
    if not TOKEN or not CHAT_ID:
        print(
            "Missing TELEGRAM_BOT_TOKEN "
            "or TELEGRAM_CHAT_ID",
            file=sys.stderr,
        )
        return 2

    if MANUAL_DISTRICT:
        return await run_manual_search()

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
        await enrich_new_listings(new_items)

        for item in new_items:
            send_listing(item)

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
