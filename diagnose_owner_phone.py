import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

TARGETS = [
    ("SS.ge", "36564570", "https://home.ss.ge/en/real-estate/1-room-Flat-For-Rent-Saburtalo-36564570"),
    ("MyHome.ge", "25884074", "https://www.myhome.ge/en/real-estate/2-room-apartment-for-rent-in-saburtalo-25884074"),
]

OUT_DIR = Path("phone_diagnostics")
OUT_DIR.mkdir(exist_ok=True)

GE_MOBILE_RE = re.compile(r"(?:\+?995[\s().-]*)?(5\d{2})(?:[\s().-]*\d){6}")
MASKED_RE = re.compile(r"(?:\+?995[\s().-]*)?5\d{2}(?:[\s().-]*\d){2,5}[\s().-]*\*{2,}")
PHONE_WORDS = (
    "phone", "show phone", "show number", "number", "call",
    "ტელეფ", "ნომერ", "დარეკ", "телефон", "номер", "показать",
)


def normalize_phone(value: str):
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("00995"):
        digits = digits[2:]
    local = digits[3:] if digits.startswith("995") else digits
    if len(local) == 9 and local.startswith("5"):
        return "+995" + local
    return None


def phones_from_text(text: str):
    found = []
    for m in GE_MOBILE_RE.finditer(text or ""):
        phone = normalize_phone(m.group(0))
        if phone and phone not in found:
            found.append(phone)
    return found


async def collect_page_state(page):
    return await page.evaluate(r'''
() => {
  const attrs = ["href","title","aria-label","data-testid","data-test","class","id","name","value"];
  const elements = [...document.querySelectorAll("a,button,[role=button],input,div,span")];
  const interesting = [];
  for (const el of elements) {
    const text = (el.innerText || el.textContent || "").trim().replace(/\s+/g, " ");
    const attrObj = {};
    for (const a of attrs) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v) attrObj[a] = v;
    }
    const fingerprint = (text + " " + Object.values(attrObj).join(" ")).toLowerCase();
    const phoneLike =
      /phone|number|call|tel:|whatsapp|ტელეფ|ნომერ|დარეკ|телефон|номер|показать/.test(fingerprint) ||
      /\*{2,}/.test(fingerprint) ||
      /(?:\+?995[\s().-]*)?5\d{2}/.test(fingerprint);
    if (phoneLike) {
      interesting.push({
        tag: el.tagName,
        text: text.slice(0, 300),
        attrs: attrObj,
        html: (el.outerHTML || "").slice(0, 1200)
      });
    }
  }
  return {
    title: document.title,
    url: location.href,
    bodyText: (document.body && document.body.innerText || "").slice(0, 200000),
    bodyHtml: (document.documentElement && document.documentElement.outerHTML || "").slice(0, 600000),
    interesting: interesting.slice(0, 300)
  };
}
''')


async def visible_phone_controls(page):
    locator = page.locator("a,button,[role=button],input")
    count = await locator.count()
    results = []
    for i in range(min(count, 1500)):
        el = locator.nth(i)
        try:
            if not await el.is_visible():
                continue
            tag = await el.evaluate("(e)=>e.tagName")
            text = "" if tag == "INPUT" else ((await el.inner_text(timeout=300)) or "")
            attrs = {}
            for name in ("href", "title", "aria-label", "data-testid", "data-test", "class", "id", "name", "value"):
                try:
                    v = await el.get_attribute(name, timeout=300)
                except Exception:
                    v = None
                if v:
                    attrs[name] = v
            fp = (text + " " + " ".join(attrs.values())).lower()
            if (
                any(word in fp for word in PHONE_WORDS)
                or "tel:" in fp
                or "**" in fp
                or re.search(r"(?:\+?995[\s().-]*)?5\d{2}", fp)
            ):
                results.append((i, text.strip(), attrs))
        except Exception:
            pass
    return results


async def click_candidate_and_compare(page, index, before_phones):
    locator = page.locator("a,button,[role=button],input").nth(index)
    try:
        await locator.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass
    try:
        await locator.click(timeout=2500, force=True)
    except Exception as exc:
        return {"clicked": False, "error": repr(exc), "new_phones": []}
    await page.wait_for_timeout(1200)
    body = await page.locator("body").inner_text(timeout=5000)
    after = phones_from_text(body)
    return {
        "clicked": True,
        "error": None,
        "new_phones": [x for x in after if x not in before_phones],
        "after_phones": after,
    }


async def diagnose(site, listing_id, url, browser):
    print(f"\n=== {site} {listing_id} ===")
    context = await browser.new_context(
        viewport={"width": 1440, "height": 1200},
        locale="en-US",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)
        print("HTTP:", response.status if response else "no-response")
        print("FINAL URL:", page.url)
        print("TITLE:", await page.title())

        state_before = await collect_page_state(page)
        body_before = state_before["bodyText"]
        before_phones = phones_from_text(body_before)
        masked_before = list(dict.fromkeys(m.group(0) for m in MASKED_RE.finditer(body_before)))
        print("VISIBLE PHONES BEFORE:", before_phones)
        print("MASKED PHONES BEFORE:", masked_before[:20])

        controls = await visible_phone_controls(page)
        print(f"PHONE-LIKE CONTROLS: {len(controls)}")
        for n, (index, text, attrs) in enumerate(controls[:40], 1):
            print(f"  [{n}] DOM_INDEX={index} TEXT={text[:120]!r} ATTRS={json.dumps(attrs, ensure_ascii=False)[:500]}")

        safe_name = f"{site.replace('.', '_')}_{listing_id}"
        (OUT_DIR / f"{safe_name}_before.json").write_text(
            json.dumps(state_before, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await page.screenshot(path=str(OUT_DIR / f"{safe_name}_before.png"), full_page=True)

        winner = None
        for pos, _ in enumerate(controls[:25], 1):
            test_page = await context.new_page()
            try:
                await test_page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await test_page.wait_for_timeout(1800)
                fresh_before = phones_from_text(await test_page.locator("body").inner_text(timeout=5000))
                fresh_controls = await visible_phone_controls(test_page)
                if pos - 1 >= len(fresh_controls):
                    continue
                fresh_index, fresh_text, fresh_attrs = fresh_controls[pos - 1]
                result = await click_candidate_and_compare(test_page, fresh_index, fresh_before)
                print(
                    f"CLICK TEST [{pos}] text={fresh_text[:80]!r} "
                    f"clicked={result.get('clicked')} new={result.get('new_phones')}"
                )
                if len(result.get("new_phones", [])) == 1:
                    winner = {
                        "candidate_number": pos,
                        "dom_index": fresh_index,
                        "text": fresh_text,
                        "attrs": fresh_attrs,
                        "phone": result["new_phones"][0],
                    }
                    after_state = await collect_page_state(test_page)
                    (OUT_DIR / f"{safe_name}_winner_after.json").write_text(
                        json.dumps(after_state, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    await test_page.screenshot(
                        path=str(OUT_DIR / f"{safe_name}_winner_after.png"),
                        full_page=True,
                    )
                    break
            except Exception as exc:
                print(f"CLICK TEST [{pos}] ERROR: {exc!r}")
            finally:
                await test_page.close()

        summary = {
            "site": site,
            "listing_id": listing_id,
            "url": url,
            "phones_before": before_phones,
            "masked_before": masked_before,
            "winner": winner,
        }
        (OUT_DIR / f"{safe_name}_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if winner:
            print("SUCCESS: one newly revealed owner-phone candidate found")
            print("PHONE:", winner["phone"])
            print("CONTROL:", winner["text"], winner["attrs"])
        else:
            print("NO UNIQUE REVEALED PHONE FOUND")
            print("Diagnostic files were saved in:", OUT_DIR.resolve())
    except Exception as exc:
        print("FATAL:", repr(exc))
    finally:
        await context.close()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            for target in TARGETS:
                await diagnose(*target, browser)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
