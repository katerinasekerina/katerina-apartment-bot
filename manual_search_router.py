"""Manual district router for the Katerina Apartment Bot.

IMPORTANT:
- Automatic production check_once.py remains untouched.
- This file affects ONLY manual district searches.
- Manual search is RENT only.
- Rooms: 1, 2, 3.
"""

import asyncio
import json
import re
import urllib.parse

import check_once


# ============================================================
# SAVE ORIGINAL CHECK_ONCE FUNCTIONS
# ============================================================

_ORIGINAL_LISTING_ID_FROM_URL = check_once.listing_id_from_url
_ORIGINAL_IS_TARGET_LOCATION = check_once.is_target_location
_ORIGINAL_COLLECT_PAGE_LINKS = check_once.collect_page_links


# ============================================================
# CURRENT MYHOME URL SUPPORT
# ============================================================

def manual_listing_id_from_url(site: str, url: str):
    """
    Support current MyHome URLs such as:

    /en/pr/25174661/2-room-apartment-for-rent-in-vashlijvari/

    while preserving all older URL formats supported by check_once.py.
    """

    try:
        parts = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(parts.path)
    except Exception:
        path = urllib.parse.unquote(url or "")

    if site == "MyHome.ge":
        patterns = (
            r"/(?:[a-z]{2}/)?pr/(\d{6,10})(?:/|$)",
            r"/real-estate/[^/?#]*-(\d{6,10})(?:/|$)",
            r"/udzravi-qoneba/[^/?#]*-(\d{6,10})(?:/|$)",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                path,
                re.IGNORECASE,
            )

            if match:
                return match.group(1)

    return _ORIGINAL_LISTING_ID_FROM_URL(
        site,
        url,
    )


# ============================================================
# MYHOME CARD COLLECTION
# ============================================================

async def manual_collect_page_links(page):
    """
    MyHome manual search:
    collect only real listing-card links.

    This avoids collecting unrelated navigation,
    recommended sections and other page links.

    SS.ge continues using the stable production collector.
    """

    current_url = str(page.url or "").lower()

    if "myhome.ge" not in current_url:
        return await _ORIGINAL_COLLECT_PAGE_LINKS(page)

    return await page.evaluate(
        r"""
        () => {
          const clean = (value) =>
            (value || '').replace(/\s+/g, ' ').trim();

          const results = [];
          const seen = new Set();

          const listingHref = (href) => {
            if (!href) return false;

            return (
              /\/[a-z]{2}\/pr\/\d{6,10}(?:\/|$)/i.test(href) ||
              /\/real-estate\/[^?#]*-\d{6,10}(?:\/|$)/i.test(href) ||
              /\/udzravi-qoneba\/[^?#]*-\d{6,10}(?:\/|$)/i.test(href)
            );
          };

          for (const anchor of document.querySelectorAll('a[href]')) {
            const href = anchor.href || '';

            if (!listingHref(href)) {
              continue;
            }

            const cleanHref = href.split('#')[0];

            if (seen.has(cleanHref)) {
              continue;
            }

            let node = anchor;
            let bestText = clean(
              anchor.innerText ||
              anchor.getAttribute('aria-label') ||
              anchor.title ||
              ''
            );

            let card = anchor;

            /*
             * Find the smallest useful card container.
             * A proper property card normally contains:
             * room count and/or area.
             */
            for (
              let depth = 0;
              depth < 7 && node;
              depth++
            ) {
              const candidate = clean(node.innerText || '');

              const propertyMarker =
                /(?:m²|m2|room|ოთახ|комнат)/i.test(candidate);

              if (
                propertyMarker &&
                candidate.length >= 20 &&
                candidate.length <= 1000
              ) {
                bestText = candidate;
                card = node;
                break;
              }

              node = node.parentElement;
            }

            /*
             * IMPORTANT:
             * We require enough card information.
             * This prevents bare recommendation/navigation
             * links from entering the search pipeline.
             */
            if (
              !bestText ||
              !/(?:room|ოთახ|комнат)/i.test(bestText)
            ) {
              continue;
            }

            let image = '';

            const images = [
              ...card.querySelectorAll('img'),
              ...anchor.querySelectorAll('img')
            ];

            for (const img of images) {
              const candidates = [
                img.currentSrc,
                img.src,
                img.getAttribute('data-src'),
                img.getAttribute('data-lazy-src'),
                img.getAttribute('data-original')
              ];

              for (const value of candidates) {
                if (
                  value &&
                  /^https?:\/\//i.test(value) &&
                  !/logo|icon|avatar|banner|advert|promo/i.test(value)
                ) {
                  image = value;
                  break;
                }
              }

              if (image) {
                break;
              }
            }

            seen.add(cleanHref);

            results.push({
              href: cleanHref,
              text: bestText,
              image: image
            });
          }

          return results;
        }
        """
    )


# ============================================================
# STRICT LOCATION + RENT SAFETY FILTER
# ============================================================

def manual_is_target_location(
    text: str,
    url: str,
    source=None,
) -> bool:
    """
    Keep district validation ACTIVE.

    We intentionally DO NOT automatically trust every MyHome
    result anymore.

    Example:
    Vashlijvari search must not accept a Lisi listing.
    """

    combined = urllib.parse.unquote(
        f"{text} {url}"
    ).lower()

    if source and source.get("manual_search"):

        # ----------------------------------------------------
        # RENT ONLY
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # TARGET DISTRICT
        # ----------------------------------------------------

        aliases = source.get(
            "district_aliases",
            (),
        )

        if aliases:
            return any(
                str(alias).lower() in combined
                for alias in aliases
            )

    return _ORIGINAL_IS_TARGET_LOCATION(
        text,
        url,
        source,
    )


# Apply patches only inside manual_search_router process.

check_once.listing_id_from_url = manual_listing_id_from_url
check_once.collect_page_links = manual_collect_page_links
check_once.is_target_location = manual_is_target_location


# ============================================================
# TBILISI DISTRICTS
# ============================================================

TBILISI_DISTRICTS = {
    "vake": {
        "label_ru": "Ваке",
        "myhome_slug": "vake",
        "ss_subdistrict_id": "47",
        "aliases": (
            "vake",
            "ვაკე",
            "ваке",
        ),
        "pages": 4,
    },

    "saburtalo": {
        "label_ru": "Сабуртало",
        "myhome_slug": "saburtalo",
        "ss_subdistrict_id": "3",
        "aliases": (
            "saburtalo",
            "საბურთალო",
            "сабуртало",
        ),
        "pages": 4,
    },

    "vashlijvari": {
        "label_ru": "Вашлиджвари",
        "myhome_slug": "vashlijvari",

        # IMPORTANT:
        # Current SS.ge Vashlijvari subdistrict ID.
        "ss_subdistrict_id": "48",

        "aliases": (
            "vashlijvari",
            "ვაშლიჯვარი",
            "вашлиджвари",
        ),
        "pages": 5,
    },

    "lisi": {
        "label_ru": "Лиси",
        "myhome_slug": "lisi",
        "ss_subdistrict_id": "3",
        "aliases": (
            "lisi lake",
            "lisi",
            "ლისი",
            "ლისის ტბა",
            "лиси",
        ),
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
        "aliases": (
            "vera",
            "ვერა",
            "вера",
        ),
        "pages": 8,
    },

    "mtatsminda": {
        "label_ru": "Мтацминда",
        "myhome_slug": "mtawminda",
        "ss_subdistrict_id": "51",
        "aliases": (
            "mtatsminda",
            "mtawminda",
            "მთაწმინდა",
            "мтацминда",
        ),
        "pages": 5,
    },

    "sololaki": {
        "label_ru": "Сололаки",
        "myhome_slug": "sololaki",
        "ss_subdistrict_id": "20,21,22,23,51,52",
        "aliases": (
            "sololaki",
            "სოლოლაკი",
            "сололаки",
        ),
        "pages": 8,
    },

    "chugureti": {
        "label_ru": "Чугурети",
        "myhome_slug": "chughureti",
        "ss_subdistrict_id": "31",
        "aliases": (
            "chugureti",
            "chughureti",
            "ჩუღურეთი",
            "чугурети",
        ),
        "pages": 5,
    },

    "avlabari": {
        "label_ru": "Авлабари",
        "myhome_slug": "avlabari",
        "ss_subdistrict_id": "20,21,22,23,51,52",
        "aliases": (
            "avlabari",
            "ავლაბარი",
            "авлабари",
        ),
        "pages": 8,
    },

    "didube": {
        "label_ru": "Дидубе",
        "myhome_slug": "didube",
        "ss_subdistrict_id": "1",
        "aliases": (
            "didube",
            "დიდუბე",
            "дидубе",
        ),
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
            "დიღომი",
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
        "aliases": (
            "nadzaladevi",
            "ნაძალადევი",
            "надзаладеви",
        ),
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
        "aliases": (
            "gldani",
            "გლდანი",
            "глдани",
        ),
        "pages": 4,
    },

    "mukhiani": {
        "label_ru": "Мухиани",
        "myhome_slug": "mukhiani",
        "ss_subdistrict_id": "40",
        "aliases": (
            "mukhiani",
            "მუხიანი",
            "мухиани",
        ),
        "pages": 5,
    },

    "temqa": {
        "label_ru": "Темка",
        "myhome_slug": "temqa",
        "ss_subdistrict_id": "37",
        "aliases": (
            "temqa",
            "temka",
            "თემქა",
            "темка",
            "темқа",
        ),
        "pages": 5,
    },

    "isani": {
        "label_ru": "Исани",
        "myhome_slug": "isani",

        # Current SS.ge Isani ID is confirmed as 10.
        "ss_subdistrict_id": "10",

        "aliases": (
            "isani",
            "ისანი",
            "исани",
        ),
        "pages": 5,
    },

    "samgori": {
        "label_ru": "Самгори",
        "myhome_slug": "samgori",
        "ss_subdistrict_id": (
            "6,7,8,9,10,11,13,24,14,15,16,17,18,19"
        ),
        "aliases": (
            "samgori",
            "სამგორი",
            "самгори",
        ),
        "pages": 8,
    },

    "varketili": {
        "label_ru": "Варкетили",
        "myhome_slug": "varketili",
        "ss_subdistrict_id": "9",
        "aliases": (
            "varketili",
            "ვარკეთილი",
            "варкетили",
        ),
        "pages": 5,
    },

    "vazisubani": {
        "label_ru": "Вазисубани",
        "myhome_slug": "vazisubani",
        "ss_subdistrict_id": (
            "6,7,8,9,10,11,13,24,14,15,16,17,18,19"
        ),
        "aliases": (
            "vazisubani",
            "ვაზისუბანი",
            "вазисубани",
        ),
        "pages": 8,
    },

    "ortachala": {
        "label_ru": "Ортачала",
        "myhome_slug": "ortachala",
        "ss_subdistrict_id": "14",
        "aliases": (
            "ortachala",
            "ორთაჭალა",
            "ортачала",
        ),
        "pages": 5,
    },

    "krtsanisi": {
        "label_ru": "Крцаниси",
        "myhome_slug": "krwanisi",
        "ss_subdistrict_id": (
            "6,7,8,9,10,11,13,24,14,15,16,17,18,19"
        ),
        "aliases": (
            "krtsanisi",
            "krwanisi",
            "კრწანისი",
            "крцаниси",
        ),
        "pages": 8,
    },

    "navtlugi": {
        "label_ru": "Навтлуги",
        "myhome_slug": "navtlugi",
        "ss_subdistrict_id": (
            "6,7,8,9,10,11,13,24,14,15,16,17,18,19"
        ),
        "aliases": (
            "navtlugi",
            "ნავთლუღი",
            "навтлуги",
        ),
        "pages": 8,
    },

    "lilo": {
        "label_ru": "Лило",
        "myhome_slug": "lilo",
        "ss_subdistrict_id": (
            "6,7,8,9,10,11,13,24,14,15,16,17,18,19"
        ),
        "aliases": (
            "lilo",
            "ლილო",
            "лило",
        ),
        "pages": 8,
    },
}


# ============================================================
# MANUAL RENT SOURCES
# ============================================================

def manual_sources_for_district(
    district_key: str,
):
    config = TBILISI_DISTRICTS[district_key]

    # --------------------------------------------------------
    # MYHOME
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # SS.GE
    # --------------------------------------------------------

    ss_query = urllib.parse.urlencode(
        {
            "cityIdList": "95",
            "subdistrictIds": str(
                config["ss_subdistrict_id"]
            ),
            "currencyId": "1",
            "advancedSearch": json.dumps(
                {
                    "individualEntityOnly": True,
                },
                separators=(",", ":"),
            ),
        }
    )

    shared = {
        "deal": "rent",
        "rooms": {
            1,
            2,
            3,
        },
        "pages": int(
            config.get(
                "pages",
                5,
            )
        ),
        "district_aliases": config["aliases"],
        "district_label": config["label_ru"],
        "manual_search": True,
    }

    return [
        {
            **shared,
            "key": (
                f"manual_myhome_{district_key}"
            ),
            "site": "MyHome.ge",
            "url": (
                "https://www.myhome.ge/en/"
                "real-estate/rent/apartment/"
                f"tbilisi/{config['myhome_slug']}/"
                f"?{myhome_query}"
            ),
        },

        {
            **shared,
            "key": (
                f"manual_ss_{district_key}"
            ),
            "site": "SS.ge",
            "url": (
                "https://home.ss.ge/en/"
                "real-estate/l/Flat/For-Rent?"
                f"{ss_query}"
            ),
        },
    ]


# ============================================================
# ENTRY POINT
# ============================================================

def main() -> int:
    """
    Patch manual configuration only.

    Automatic production continues:

    check-apartments.yml
        ->
    check_once.py

    without using this router.
    """

    check_once.DISTRICTS = (
        TBILISI_DISTRICTS
    )

    check_once.manual_sources_for_district = (
        manual_sources_for_district
    )

    return asyncio.run(
        check_once.main()
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
