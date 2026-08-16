"""Manual district router for the Katerina Apartment Bot.

This file intentionally leaves the stable production check_once.py untouched.
It injects the extended Tbilisi district map only for MANUAL_DISTRICT runs.

Manual search:
- RENT only
- Apartments only
- 1, 2 or 3 rooms
- Current MyHome /en/pr/<ID>/ URLs supported
"""

import asyncio
import json
import re
import urllib.parse

import check_once


# ---------------------------------------------------------------------------
# MANUAL-SEARCH PATCHES
# ---------------------------------------------------------------------------

_ORIGINAL_LISTING_ID_FROM_URL = check_once.listing_id_from_url
_ORIGINAL_IS_TARGET_LOCATION = check_once.is_target_location


def manual_listing_id_from_url(site: str, url: str):
    """Support current MyHome /en/pr/<ID>/ listing URLs."""

    try:
        path = urllib.parse.unquote(
            urllib.parse.urlsplit(url).path
        )
    except Exception:
        path = urllib.parse.unquote(url or "")

    if site == "MyHome.ge":
        match = re.search(
            r"/(?:[a-z]{2}/)?pr/(\d{6,10})(?:/|$)",
            path,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return _ORIGINAL_LISTING_ID_FROM_URL(site, url)


def manual_is_target_location(
    text: str,
    url: str,
    source=None,
) -> bool:
    """
    Manual-search location handling.

    MyHome:
    The search URL itself is already district-specific, so do not reject
    valid cards just because the card text/URL does not repeat the district.

    SS.ge:
    Keep the existing district-alias verification because one SS subdistrict
    ID can sometimes cover a wider area.
    """

    combined = urllib.parse.unquote(
        f"{text} {url}"
    ).lower()

    if source and source.get("manual_search"):

        # Manual search is RENT ONLY.
        sale_markers = (
            "for sale",
            "/for-sale",
            "flat-for-sale",
            "apartment-for-sale",
            "house-for-sale",
            "იყიდება",
            "продается",
            "продаётся",
        )

        if any(
            marker in combined
            for marker in sale_markers
        ):
            return False

        # MyHome manual URL is already scoped to the selected district.
        # Do not apply the second card-text district filter.
        if source.get("site") == "MyHome.ge":
            return True

    # Keep strict district matching for SS.ge and all other cases.
    return _ORIGINAL_IS_TARGET_LOCATION(
        text,
        url,
        source,
    )


check_once.listing_id_from_url = manual_listing_id_from_url
check_once.is_target_location = manual_is_target_location


# ---------------------------------------------------------------------------
# TBILISI DISTRICTS
# ---------------------------------------------------------------------------

TBILISI_DISTRICTS = {
    "vake": {
        "label_ru": "Ваке",
        "myhome_slug": "vake",
        "ss_subdistrict_id": "47",
        "aliases": ("vake", "ვაკე", "ваке"),
        "pages": 4,
    },
    "saburtalo": {
        "label_ru": "Сабуртало",
        "myhome_slug": "saburtalo",
        "ss_subdistrict_id": "3",
        "aliases": ("saburtalo", "საბურთალო", "сабуртало"),
        "pages": 4,
    },
    "vashlijvari": {
        "label_ru": "Вашлиджвари",
        "myhome_slug": "vashlijvari",
        "ss_subdistrict_id": "3",
        "aliases": ("vashlijvari", "ვაშლიჯვარი", "вашлиджвари"),
        "pages": 5,
    },
    "lisi": {
        "label_ru": "Лиси",
        "myhome_slug": "lisi",
        "ss_subdistrict_id": "3",
        "aliases": ("lisi lake", "lisi", "ლისი", "ლისის ტბა", "лиси"),
        "pages": 5,
    },
    "nutsubidze": {
        "label_ru": "Плато Нуцубидзе",
        "myhome_slug": "nucubidzis-perdobi",
        "ss_subdistrict_id": "3",
        "aliases": (
            "nutsubidze plateau",
            "nucubidze",
            "ნუცუბიძის პლ",
            "ნუცუბიძის ფერდობი",
            "нуцубидзе",
        ),
        "pages": 5,
    },
    "vera": {
        "label_ru": "Вера",
        "myhome_slug": "vera",
        "ss_subdistrict_id": "20,21,22,23,51,52",
        "aliases": ("vera", "ვერა", "вера"),
        "pages": 8,
    },
    "mtatsminda": {
        "label_ru": "Мтацминда",
        "myhome_slug": "mtawminda",
        "ss_subdistrict_id": "51",
        "aliases": ("mtatsminda", "mtawminda", "მთაწმინდა", "мтацминда"),
        "pages": 5,
    },
    "sololaki": {
        "label_ru": "Сололаки",
        "myhome_slug": "sololaki",
        "ss_subdistrict_id": "20,21,22,23,51,52",
        "aliases": ("sololaki", "სოლოლაკი", "сололаки"),
        "pages": 8,
    },
    "chugureti": {
        "label_ru": "Чугурети",
        "myhome_slug": "chughureti",
        "ss_subdistrict_id": "31",
        "aliases": ("chugureti", "chughureti", "ჩუღურეთი", "чугурети"),
        "pages": 5,
    },
    "avlabari": {
        "label_ru": "Авлабари",
        "myhome_slug": "avlabari",
        "ss_subdistrict_id": "20,21,22,23,51,52",
        "aliases": ("avlabari", "ავლაბარი", "авлабари"),
        "pages": 8,
    },
    "didube": {
        "label_ru": "Дидубе",
        "myhome_slug": "didube",
        "ss_subdistrict_id": "1",
        "aliases": ("didube", "დიდუბე", "дидубе"),
        "pages": 4,
    },
    "digomi": {
        "label_ru": "Дигоми",
        "myhome_slug": "dighmis-masivi",
        "ss_subdistrict_id": "28",
        "aliases": (
            "dighmis masivi",
            "dighmis-masivi",
            "digomi",
            "დიღმის მასივი",
            "дидгомский массив",
            "дигоми",
        ),
        "pages": 5,
    },
    "didi_digomi": {
        "label_ru": "Диди Дигоми",
        "myhome_slug": "didi-dighomi",
        "ss_subdistrict_id": "45",
        "aliases": (
            "didi digomi",
            "didi-dighomi",
            "დიდი დიღომი",
            "диди дигоми",
        ),
        "pages": 5,
    },
    "nadzaladevi": {
        "label_ru": "Надзаладеви",
        "myhome_slug": "nadzaladevi",
        "ss_subdistrict_id": "41",
        "aliases": ("nadzaladevi", "ნაძალადევი", "надзаладеви"),
        "pages": 5,
    },
    "sanzona": {
        "label_ru": "Санзона",
        "myhome_slug": "san-zona",
        "ss_subdistrict_id": "42",
        "aliases": (
            "sanzona",
            "san zona",
            "san-zona",
            "სანზონა",
            "санзона",
        ),
        "pages": 5,
    },
    "gldani": {
        "label_ru": "Глдани",
        "myhome_slug": "gldani",
        "ss_subdistrict_id": "33",
        "aliases": ("gldani", "გლდანი", "глдани"),
        "pages": 4,
    },
    "mukhiani": {
        "label_ru": "Мухиани",
        "myhome_slug": "mukhiani",
        "ss_subdistrict_id": "40",
        "aliases": ("mukhiani", "მუხიანი", "мухиани"),
        "pages": 5,
    },
    "temqa": {
        "label_ru": "Темка",
        "myhome_slug": "temqa",
        "ss_subdistrict_id": "37",
        "aliases": ("temqa", "temka", "თემქა", "темка", "темқа"),
        "pages": 5,
    },
    "isani": {
        "label_ru": "Исани",
        "myhome_slug": "isani",
        "ss_subdistrict_id": "10",
        "aliases": ("isani", "ისანი", "исани"),
        "pages": 5,
    },
    "samgori": {
        "label_ru": "Самгори",
        "myhome_slug": "samgori",
        "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19",
        "aliases": ("samgori", "სამგორი", "самгори"),
        "pages": 8,
    },
    "varketili": {
        "label_ru": "Варкетили",
        "myhome_slug": "varketili",
        "ss_subdistrict_id": "9",
        "aliases": ("varketili", "ვარკეთილი", "варкетили"),
        "pages": 5,
    },
    "vazisubani": {
        "label_ru": "Вазисубани",
        "myhome_slug": "vazisubani",
        "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19",
        "aliases": ("vazisubani", "ვაზისუბანი", "вазисубани"),
        "pages": 8,
    },
    "ortachala": {
        "label_ru": "Ортачала",
        "myhome_slug": "ortachala",
        "ss_subdistrict_id": "14",
        "aliases": ("ortachala", "ორთაჭალა", "ортачала"),
        "pages": 5,
    },
    "krtsanisi": {
        "label_ru": "Крцаниси",
        "myhome_slug": "krwanisi",
        "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19",
        "aliases": ("krtsanisi", "krwanisi", "კრწანისი", "крцаниси"),
        "pages": 8,
    },
    "navtlugi": {
        "label_ru": "Навтлуги",
        "myhome_slug": "navtlugi",
        "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19",
        "aliases": ("navtlugi", "ნავთლუღი", "навтлуги"),
        "pages": 8,
    },
    "lilo": {
        "label_ru": "Лило",
        "myhome_slug": "lilo",
        "ss_subdistrict_id": "6,7,8,9,10,11,13,24,14,15,16,17,18,19",
        "aliases": ("lilo", "ლილო", "лило"),
        "pages": 8,
    },
}


# ---------------------------------------------------------------------------
# MANUAL RENT SOURCES
# ---------------------------------------------------------------------------

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
    # Only manual-search behavior is patched.
    # Automatic check_once.py production monitoring remains unchanged.
    check_once.DISTRICTS = TBILISI_DISTRICTS
    check_once.manual_sources_for_district = manual_sources_for_district

    return asyncio.run(check_once.main())


if __name__ == "__main__":
    raise SystemExit(main())
