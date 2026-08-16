"""Manual district router for the Katerina Apartment Bot.

Manual search only:
- RENT
- Apartment
- 1–3 rooms
- Exact selected district
- MyHome.ge + SS.ge
- Last 24 hours only
- Max results controlled by MANUAL_LIMIT
"""

import asyncio
import json
import re
import urllib.parse
from datetime import datetime, timedelta

import check_once


_ORIGINAL_LISTING_ID_FROM_URL = check_once.listing_id_from_url
_ORIGINAL_COLLECT_PAGE_LINKS = check_once.collect_page_links
_ORIGINAL_IS_TARGET_LOCATION = check_once.is_target_location
_ORIGINAL_SELECT_MANUAL_LISTINGS = check_once.select_manual_listings


TBILISI_DISTRICTS = {
    "vake": {"label_ru": "Ваке", "myhome_slug": "vake", "ss_subdistrict_id": "47", "aliases": ("vake", "ვაკე", "ваке"), "url_aliases": ("vake",), "pages": 4},
    "saburtalo": {"label_ru": "Сабуртало", "myhome_slug": "saburtalo", "ss_subdistrict_id": "3", "aliases": ("saburtalo", "საბურთალო", "сабуртало"), "url_aliases": ("saburtalo",), "pages": 4},
    "vashlijvari": {"label_ru": "Вашлиджвари", "myhome_slug": "vashlijvari", "ss_subdistrict_id": "48", "aliases": ("vashlijvari", "vaslidzvari", "ვაშლიჯვარი", "вашлиджвари"), "url_aliases": ("vashlijvari", "vaslidzvari"), "pages": 5},
    "lisi": {"label_ru": "Лиси", "myhome_slug": "lisi", "ss_subdistrict_id": "3", "aliases": ("lisi lake", "lisi", "ლისი", "ლისის ტბა", "лиси"), "url_aliases": ("lisi-lake", "lisi"), "pages": 5},
    "nutsubidze": {"label_ru": "Плато Нуцубидзе", "myhome_slug": "nucubidzis-perdobi", "ss_subdistrict_id": "3", "aliases": ("nutsubidze plateau", "nutsubidze", "nucubidze", "ნუცუბიძის პლ", "ნუცუბიძის ფერდობი", "нуцубидзе"), "url_aliases": ("nutsubidze-plateau", "nutsubidze", "nucubidze", "nucubidzis-perdobi"), "pages": 5},
    "vera": {"label_ru": "Вера", "myhome_slug": "vera", "ss_subdistrict_id": "20,21,22,23,51,52", "aliases": ("vera", "ვერა", "вера"), "url_aliases": ("vera",), "pages": 8},
    "mtatsminda": {"label_ru": "Мтацминда", "myhome_slug": "mtawminda", "ss_subdistrict_id": "51", "aliases": ("mtatsminda", "mtawminda", "მთაწმინდა", "мтацминда"), "url_aliases": ("mtatsminda", "mtawminda"), "pages": 5},
    "sololaki": {"label_ru": "Сололаки", "myhome_slug": "sololaki", "ss_subdistrict_id": "20,21,22,23,51,52", "aliases": ("sololaki", "სოლოლაკი", "сололаки"), "url_aliases": ("sololaki",), "pages": 8},
    "chugureti": {"label_ru": "Чугурети", "myhome_slug": "chughureti", "ss_subdistrict_id": "31", "aliases": ("chugureti", "chughureti", "ჩუღურეთი", "чугурети"), "url_aliases": ("chugureti", "chughureti"), "pages": 5},
    "avlabari": {"label_ru": "Авлабари", "myhome_slug": "avlabari", "ss_subdistrict_id": "20,21,22,23,51,52", "aliases": ("avlabari", "ავლაბარი", "авлабари"), "url_aliases": ("avlabari",), "pages": 8},
    "didube": {"label_ru": "Дидубе", "myhome_slug": "didube", "ss_subdistrict_id": "1", "aliases": ("didube", "დიდუბე", "дидубе"), "url_aliases": ("didube",), "pages": 4},
    "digomi": {"label_ru": "Дигоми", "myhome_slug": "dighmis-masivi", "ss_subdistrict_id": "28", "aliases": ("dighmis masivi", "dighmis-masivi", "digomi", "dighomi", "დიღომი", "დიღმის მასივი", "дигоми"), "url_aliases": ("dighmis-masivi", "dighomi", "digomi"), "pages": 5},
    "didi_digomi": {"label_ru": "Диди Дигоми", "myhome_slug": "didi-dighomi", "ss_subdistrict_id": "45", "aliases": ("didi digomi", "didi-dighomi", "დიდი დიღომი", "диди дигоми"), "url_aliases": ("didi-dighomi", "didi-digomi"), "pages": 5},
    "nadzaladevi": {"label_ru": "Надзаладеви", "myhome_slug": "nadzaladevi", "ss_subdistrict_id": "41", "aliases": ("nadzaladevi", "ნაძალადევი", "надзаладеви"), "url_aliases": ("nadzaladevi",), "pages": 5},
    "sanzona": {"label_ru": "Санзона", "myhome_slug": "san-zona", "ss_subdistrict_id": "42", "aliases": ("sanzona", "san zona", "san-zona", "სანზონა", "санзона"), "url_aliases": ("sanzona", "san-zona"), "pages": 5},
    "gldani": {"label_ru": "Глдани", "myhome_slug": "gldani", "ss_subdistrict_id": "33", "aliases": ("gldani", "გლდანი", "глдани"), "url_aliases": ("gldani",), "pages": 4},
    "mukhiani": {"label_ru": "Мухиани", "myhome_slug": "mukhiani", "ss_subdistrict_id": "40", "aliases": ("mukhiani", "მუხიანი", "мухиани"), "url_aliases": ("mukhiani",), "pages": 5},
    "temqa": {"label_ru": "Темка", "myhome_slug": "temqa", "ss_subdistrict_id": "37", "aliases": ("temqa", "temka", "თემქა", "темка"), "url_aliases": ("temqa", "temka"), "pages": 5},
    "isani": {"label_ru": "Исани", "myhome_slug": "isani", "ss_subdistrict_id": "10", "aliases": ("isani", "ისანი", "исани"), "url_aliases": ("isani",), "pages": 5},
    "samgori": {"label_ru": "Самгори", "myhome_slug": "samgori", "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19", "aliases": ("samgori", "სამგორი", "самгори"), "url_aliases": ("samgori",), "pages": 8},
    "varketili": {"label_ru": "Варкетили", "myhome_slug": "varketili", "ss_subdistrict_id": "9", "aliases": ("varketili", "ვარკეთილი", "варкетили"), "url_aliases": ("varketili",), "pages": 5},
    "vazisubani": {"label_ru": "Вазисубани", "myhome_slug": "vazisubani", "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19", "aliases": ("vazisubani", "ვაზისუბანი", "вазисубани"), "url_aliases": ("vazisubani",), "pages": 8},
    "ortachala": {"label_ru": "Ортачала", "myhome_slug": "ortachala", "ss_subdistrict_id": "14", "aliases": ("ortachala", "ორთაჭალა", "ортачала"), "url_aliases": ("ortachala",), "pages": 5},
    "krtsanisi": {"label_ru": "Крцаниси", "myhome_slug": "krwanisi", "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19", "aliases": ("krtsanisi", "krwanisi", "კრწანისი", "крцаниси"), "url_aliases": ("krtsanisi", "krwanisi"), "pages": 8},
    "navtlugi": {"label_ru": "Навтлуги", "myhome_slug": "navtlugi", "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19", "aliases": ("navtlugi", "ნავთლუღი", "навтлуги"), "url_aliases": ("navtlugi",), "pages": 8},
    "lilo": {"label_ru": "Лило", "myhome_slug": "lilo", "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19", "aliases": ("lilo", "ლილო", "лило"), "url_aliases": ("lilo",), "pages": 8},
}


def _normalized_url_path(url: str) -> str:
    try:
        return urllib.parse.unquote(urllib.parse.urlsplit(url).path).lower()
    except Exception:
        return urllib.parse.unquote(url or "").lower()


def manual_listing_id_from_url(site: str, url: str):
    path = _normalized_url_path(url)

    if site == "MyHome.ge":
        for pattern in (
            r"/(?:[a-z]{2}/)?pr/(\d{6,10})(?:/|$)",
            r"/real-estate/[^/?#]*-(\d{6,10})(?:/|$)",
            r"/udzravi-qoneba/[^/?#]*-(\d{6,10})(?:/|$)",
            # Current localized MyHome URLs, e.g.
            # /ru/nedvizhimost/sdaetsia-2-komnatnaia-kvartira-v-vaslidzvari-25771293/
            # /en/real-estate/2-room-apartment-for-rent-in-vashlijvari-25771293/
            r"/(?:[a-z]{2}/)?[^/?#]+/[^/?#]*-(\d{6,10})(?:/|$)",
        ):
            match = re.search(pattern, path, re.IGNORECASE)
            if match:
                return match.group(1)

    return _ORIGINAL_LISTING_ID_FROM_URL(site, url)


async def manual_collect_page_links(page):
    """
    MYHOME DIAGNOSTIC/FIX STEP.

    For MyHome only:
    - collect every real listing-shaped anchor, including /en/pr/<ID>/...
    - do NOT require a specific card DOM structure
    - print diagnostics to GitHub Actions logs

    SS.ge is deliberately left on the original production collector in this
    step so we can isolate the MyHome problem first.
    """
    current_url = str(page.url or "").lower()

    if "myhome.ge" not in current_url:
        return await _ORIGINAL_COLLECT_PAGE_LINKS(page)

    payload = await page.evaluate(
        r"""
        () => {
          const clean = (value) =>
            (value || '').replace(/\s+/g, ' ').trim();

          const allAnchors = Array.from(document.querySelectorAll('a[href]'));
          const results = [];
          const seen = new Set();
          const numericSamples = [];

          const isListing = (href) => {
            if (!href) return false;

            try {
              const u = new URL(href, document.baseURI);
              const path = decodeURIComponent(u.pathname || '');

              return (
                /\/(?:[a-z]{2}\/)?pr\/\d{6,10}(?:\/|$)/i.test(path) ||
                /\/real-estate\/[^?#]*-\d{6,10}(?:\/|$)/i.test(path) ||
                /\/udzravi-qoneba\/[^?#]*-\d{6,10}(?:\/|$)/i.test(path) ||
                /\/(?:[a-z]{2}\/)?[^/?#]+\/[^/?#]*-\d{6,10}(?:\/|$)/i.test(path)
              );
            } catch (_) {
              return false;
            }
          };

          const bestCardText = (anchor) => {
            let node = anchor;
            let best = clean(
              anchor.innerText ||
              anchor.getAttribute('aria-label') ||
              anchor.title ||
              ''
            );

            for (let depth = 0; depth < 8 && node; depth++) {
              const candidate = clean(node.innerText || '');

              if (
                candidate.length >= 10 &&
                candidate.length <= 1600 &&
                candidate.length > best.length
              ) {
                best = candidate;
              }

              if (
                /(?:m²|m2|room|ოთახ|комнат)/i.test(candidate) &&
                candidate.length >= 15 &&
                candidate.length <= 1600
              ) {
                return candidate;
              }

              node = node.parentElement;
            }

            return best;
          };

          const imageFrom = (anchor) => {
            let node = anchor;

            for (let depth = 0; depth < 7 && node; depth++) {
              for (const img of node.querySelectorAll('img')) {
                const values = [
                  img.currentSrc,
                  img.src,
                  img.getAttribute('data-src'),
                  img.getAttribute('data-lazy-src'),
                  img.getAttribute('data-original')
                ];

                for (const value of values) {
                  if (
                    value &&
                    /^https?:\/\//i.test(value) &&
                    !/logo|icon|avatar|banner|advert|promo|favicon/i.test(value)
                  ) {
                    return value;
                  }
                }
              }

              node = node.parentElement;
            }

            return '';
          };

          for (const anchor of allAnchors) {
            const href = anchor.href || '';

            if (/\d{6,10}/.test(href) && numericSamples.length < 12) {
              numericSamples.push(href);
            }

            if (!isListing(href)) {
              continue;
            }

            const cleanHref = href.split('#')[0];

            if (seen.has(cleanHref)) {
              continue;
            }

            seen.add(cleanHref);

            results.push({
              href: cleanHref,
              text: bestCardText(anchor),
              image: imageFrom(anchor)
            });
          }

          return {
            totalAnchors: allAnchors.length,
            listingCandidates: results.length,
            numericSamples,
            resultSamples: results.slice(0, 10).map(x => x.href),
            results
          };
        }
        """
    )

    print(
        "MYHOME_DIAG "
        f"url={current_url} "
        f"anchors={payload.get('totalAnchors', 0)} "
        f"listing_candidates={payload.get('listingCandidates', 0)}"
    )
    print(
        "MYHOME_DIAG numeric_samples="
        + json.dumps(payload.get("numericSamples", []), ensure_ascii=False)
    )
    print(
        "MYHOME_DIAG result_samples="
        + json.dumps(payload.get("resultSamples", []), ensure_ascii=False)
    )

    return list(payload.get("results", []))


def manual_is_target_location(text: str, url: str, source=None) -> bool:
    if not source or not source.get("manual_search"):
        return _ORIGINAL_IS_TARGET_LOCATION(text, url, source)

    combined = urllib.parse.unquote(f"{text} {url}").lower()

    if any(marker in combined for marker in (
        "for sale",
        "/for-sale",
        "flat-for-sale",
        "apartment-for-sale",
        "house-for-sale",
        "იყიდება",
        "продается",
        "продаётся",
    )):
        return False

    path = re.sub(r"[_\s]+", "-", _normalized_url_path(url))

    aliases = tuple(
        str(value).lower().replace(" ", "-")
        for value in source.get("district_url_aliases", ())
        if str(value).strip()
    )

    return bool(aliases) and any(alias in path for alias in aliases)


_MONTHS = {
    "jan": 1, "january": 1, "янв": 1, "января": 1, "იან": 1, "იანვ": 1, "იანვარი": 1,
    "feb": 2, "february": 2, "фев": 2, "февраля": 2, "თებ": 2, "თებერვალი": 2,
    "mar": 3, "march": 3, "мар": 3, "марта": 3, "მარ": 3, "მარტი": 3,
    "apr": 4, "april": 4, "апр": 4, "апреля": 4, "აპრ": 4, "აპრილი": 4,
    "may": 5, "мая": 5, "მაი": 5, "მაისი": 5,
    "jun": 6, "june": 6, "июн": 6, "июня": 6, "ივნ": 6, "ივნისი": 6,
    "jul": 7, "july": 7, "июл": 7, "июля": 7, "ივლ": 7, "ივლისი": 7,
    "aug": 8, "august": 8, "авг": 8, "августа": 8, "აგვ": 8, "აგვისტო": 8,
    "sep": 9, "sept": 9, "september": 9, "сен": 9, "сент": 9, "сентября": 9, "სექ": 9, "სექტ": 9, "სექტემბერი": 9,
    "oct": 10, "october": 10, "окт": 10, "октября": 10, "ოქტ": 10, "ოქტომბერი": 10,
    "nov": 11, "november": 11, "ноя": 11, "ноября": 11, "ნოე": 11, "ნოემბერი": 11,
    "dec": 12, "december": 12, "дек": 12, "декабря": 12, "დეკ": 12, "დეკემბერი": 12,
}


def _parse_card_datetime(text: str, now: datetime) -> datetime | None:
    normalized = " ".join((text or "").split()).lower()

    for pattern, unit in (
        (r"(\d+)\s*(?:sec|secs|second|seconds)\s+ago", "seconds"),
        (r"(\d+)\s*(?:min|mins|minute|minutes)\s+ago", "minutes"),
        (r"(\d+)\s*(?:hour|hours|hr|hrs)\s+ago", "hours"),
        (r"(\d+)\s*(?:წუთის|წუთი)\s*წინ", "minutes"),
        (r"(\d+)\s*(?:საათის|საათი)\s*წინ", "hours"),
        (r"(\d+)\s*(?:минут|минуты|минута)\s*назад", "minutes"),
        (r"(\d+)\s*(?:час|часа|часов)\s*назад", "hours"),
    ):
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            return now - timedelta(**{unit: int(match.group(1))})

    match = re.search(
        r"(?:today|დღეს|сегодня)[^\d]{0,12}(\d{1,2}):(\d{2})",
        normalized,
        re.IGNORECASE,
    )
    if match:
        return now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)

    match = re.search(
        r"(?:yesterday|გუშინ|вчера)[^\d]{0,12}(\d{1,2}):(\d{2})",
        normalized,
        re.IGNORECASE,
    )
    if match:
        base = now - timedelta(days=1)
        return base.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)

    match = re.search(
        r"\b(\d{1,2})\s+([A-Za-zА-Яа-яЁёႠ-ჿ]{3,12})"
        r"(?:\s+(\d{4}))?(?:[,\s]+(\d{1,2}):(\d{2}))?",
        normalized,
        re.IGNORECASE,
    )

    if not match:
        return None

    day = int(match.group(1))
    month_word = match.group(2).lower().strip(".")
    month = _MONTHS.get(month_word)

    if month is None:
        for key, value in _MONTHS.items():
            if month_word.startswith(key) or key.startswith(month_word):
                month = value
                break

    if month is None:
        return None

    year = int(match.group(3)) if match.group(3) else now.year
    hour = int(match.group(4)) if match.group(4) else 0
    minute = int(match.group(5)) if match.group(5) else 0

    try:
        candidate = datetime(year, month, day, hour, minute)
    except ValueError:
        return None

    if not match.group(3) and candidate > now + timedelta(days=2):
        candidate = candidate.replace(year=year - 1)

    return candidate


def is_fresh_manual_listing(item: dict, hours: int = 24) -> bool:
    now = datetime.now()
    published = _parse_card_datetime(str(item.get("summary") or ""), now)

    if published is None:
        return False

    age = now - published
    return timedelta(0) <= age <= timedelta(hours=hours)


def manual_select_manual_listings(listings: list[dict], limit: int):
    # Diagnostic stage: MyHome is allowed through without freshness filtering
    # so we can prove the collector works. SS.ge still uses the 24h rule.
    fresh = [
        item
        for item in listings
        if item.get("site") == "MyHome.ge"
        or is_fresh_manual_listing(item, 24)
    ]

    raw_by_site = {}
    fresh_by_site = {}

    for item in listings:
        site = item.get("site", "?")
        raw_by_site[site] = raw_by_site.get(site, 0) + 1

    for item in fresh:
        site = item.get("site", "?")
        fresh_by_site[site] = fresh_by_site.get(site, 0) + 1

    print(
        "Manual freshness filter: "
        f"raw={len(listings)} {raw_by_site}; "
        f"fresh_24h={len(fresh)} {fresh_by_site}; "
        f"dropped={len(listings) - len(fresh)}"
    )

    return _ORIGINAL_SELECT_MANUAL_LISTINGS(fresh, limit)


def manual_sources_for_district(district_key: str):
    config = TBILISI_DISTRICTS[district_key]

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
        "pages": int(config.get("pages", 5)),
        "district_aliases": config["aliases"],
        "district_url_aliases": config["url_aliases"],
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


def main() -> int:
    check_once.DISTRICTS = TBILISI_DISTRICTS
    check_once.manual_sources_for_district = manual_sources_for_district
    check_once.listing_id_from_url = manual_listing_id_from_url
    check_once.collect_page_links = manual_collect_page_links
    check_once.is_target_location = manual_is_target_location
    check_once.select_manual_listings = manual_select_manual_listings

    return asyncio.run(check_once.main())


if __name__ == "__main__":
    raise SystemExit(main())
