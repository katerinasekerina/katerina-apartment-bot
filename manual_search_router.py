"""Katerina Apartment Bot — manual_search_router FINAL_REBUILD_V3_MYHOME_PHOTO

Rules:
- MyHome.ge + SS.ge
- Rent only
- Apartments only
- 1/2/3 rooms
- Exact selected district only
- Owner / individual only
- Real listing photo
- Recent listings first
- Maximum 30
- Target 15/15 balance with automatic fill from the other source
"""

from __future__ import annotations

import asyncio, json, os, re, urllib.parse
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright
import check_once

DISTRICTS = {
    "vake": ("Ваке", "vake", "47", {"vake"}),
    "saburtalo": ("Сабуртало", "saburtalo", "3", {"saburtalo"}),
    "vashlijvari": ("Вашлиджвари", "vashlijvari", "48", {"vashlijvari", "vaslidzvari"}),
    "lisi": ("Лиси", "lisi", "3", {"lisi", "lisi-lake"}),
    "nutsubidze": ("Плато Нуцубидзе", "nucubidzis-perdobi", "3", {"nutsubidze", "nutsubidze-plateau", "nucubidze", "nucubidze-plateau", "nucubidzis-perdobi"}),
    "vera": ("Вера", "vera", "20,21,22,23,51,52", {"vera"}),
    "mtatsminda": ("Мтацминда", "mtawminda", "51", {"mtatsminda", "mtawminda"}),
    "sololaki": ("Сололаки", "sololaki", "20,21,22,23,51,52", {"sololaki"}),
    "chugureti": ("Чугурети", "chughureti", "31", {"chugureti", "chughureti"}),
    "avlabari": ("Авлабари", "avlabari", "20,21,22,23,51,52", {"avlabari"}),
    "didube": ("Дидубе", "didube", "1", {"didube"}),
    "digomi": ("Дигоми", "dighmis-masivi", "28", {"digomi", "dighomi", "dighmis-masivi"}),
    "didi_digomi": ("Диди Дигоми", "didi-dighomi", "45", {"didi-digomi", "didi-dighomi"}),
    "nadzaladevi": ("Надзаладеви", "nadzaladevi", "41", {"nadzaladevi"}),
    "sanzona": ("Санзона", "san-zona", "42", {"sanzona", "san-zona"}),
    "gldani": ("Глдани", "gldani", "33", {"gldani"}),
    "mukhiani": ("Мухиани", "mukhiani", "40", {"mukhiani"}),
    "temqa": ("Темка", "temqa", "37", {"temqa", "temka"}),
    "isani": ("Исани", "isani", "10", {"isani"}),
    "samgori": ("Самгори", "samgori", "6,7,8,9,10,11,13,24,14,15,16,17,18,19", {"samgori"}),
    "varketili": ("Варкетили", "varketili", "9", {"varketili"}),
    "vazisubani": ("Вазисубани", "vazisubani", "6,7,8,9,10,11,13,24,14,15,16,17,18,19", {"vazisubani"}),
    "ortachala": ("Ортачала", "ortachala", "14", {"ortachala"}),
    "krtsanisi": ("Крцаниси", "krwanisi", "6,7,8,9,10,11,13,24,14,15,16,17,18,19", {"krtsanisi", "krwanisi"}),
    "navtlugi": ("Навтлуги", "navtlugi", "6,7,8,9,10,11,13,24,14,15,16,17,18,19", {"navtlugi"}),
    "lilo": ("Лило", "lilo", "6,7,8,9,10,11,13,24,14,15,16,17,18,19", {"lilo"}),
}

DISTRICT = os.getenv("MANUAL_DISTRICT", "").strip().lower()
LIMIT = max(1, min(30, int(os.getenv("MANUAL_LIMIT", "30"))))
FRESH_HOURS = max(24, min(168, int(os.getenv("MANUAL_FRESH_HOURS", "24"))))
TZ = ZoneInfo("Asia/Tbilisi")

MONTHS = {
    "jan":1,"january":1,"янв":1,"января":1,"იან":1,"იანვ":1,"იანვარი":1,
    "feb":2,"february":2,"фев":2,"февраля":2,"თებ":2,"თებერვალი":2,
    "mar":3,"march":3,"мар":3,"марта":3,"მარ":3,"მარტი":3,
    "apr":4,"april":4,"апр":4,"апреля":4,"აპრ":4,"აპრილი":4,
    "may":5,"мая":5,"მაი":5,"მაისი":5,
    "jun":6,"june":6,"июн":6,"июня":6,"ივნ":6,"ივნისი":6,
    "jul":7,"july":7,"июл":7,"июля":7,"ივლ":7,"ივლისი":7,
    "aug":8,"august":8,"авг":8,"августа":8,"აგვ":8,"აგვისტო":8,
    "sep":9,"sept":9,"september":9,"сен":9,"сент":9,"сентября":9,"სექ":9,"სექტ":9,"სექტემბერი":9,
    "oct":10,"october":10,"окт":10,"октября":10,"ოქტ":10,"ოქტომბერი":10,
    "nov":11,"november":11,"ноя":11,"ноября":11,"ნოე":11,"ნოემბერი":11,
    "dec":12,"december":12,"дек":12,"декабря":12,"დეკ":12,"დეკემბერი":12,
}


def path_of(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path)


def listing_id(site: str, url: str) -> str | None:
    p = path_of(url)
    pats = [r"/real-estate/(?!l/)[^/?#]*-(\d{6,10})(?:[/?#]|$)"] if site == "SS.ge" else [
        r"/(?:[a-z]{2}/)?pr/(\d{6,10})(?:/|$)",
        r"/(?:[a-z]{2}/)?real-estate/(\d{6,10})(?:/|$)",
        r"/(?:[a-z]{2}/)?real-estate/[^/?#]*-(\d{6,10})(?:/|$)",
        r"/(?:[a-z]{2}/)?nedvizhimost/[^/?#]*-(\d{6,10})(?:/|$)",
    ]
    for pat in pats:
        m = re.search(pat, p, re.I)
        if m: return m.group(1)
    return None


def room_from_url(site: str, url: str) -> int | None:
    p = path_of(url)
    pats = [r"/([123])-room-Flat-For-Rent-"] if site == "SS.ge" else [
        r"/([123])-room-apartment-for-rent-in-", r"/sdaetsia-([123])-komnatnaia-kvartira-v-"
    ]
    for pat in pats:
        m = re.search(pat, p, re.I)
        if m: return int(m.group(1))
    return None


def district_from_url(site: str, url: str) -> str | None:
    last = path_of(url).strip("/").split("/")[-1].lower()
    if site == "SS.ge":
        m = re.match(r"^[123]-room-flat-for-rent-(.+?)-\d{6,10}$", last, re.I)
    else:
        m = re.match(r"^[123]-room-apartment-for-rent-in-(.+?)(?:-\d{6,10})?$", last, re.I)
        if not m:
            m = re.match(r"^sdaetsia-[123]-komnatnaia-kvartira-v-(.+?)(?:-\d{6,10})?$", last, re.I)
    return m.group(1).lower() if m else None


def exact_district(site: str, url: str, aliases: set[str]) -> bool:
    slug = district_from_url(site, url)
    return bool(slug and slug in {x.lower() for x in aliases})


def search_url(site: str, myhome_slug: str, ss_id: str, page: int) -> str:
    if site == "MyHome.ge":
        # MyHome owner status is verified on the detail page, not trusted from promo blocks.
        q = urllib.parse.urlencode({"deal_types":"2","real_estate_types":"1","cities":"1","currency_id":"1","CardView":"1","owner_type":"physical","room_types":"1,2,3","page":str(page)})
        return f"https://www.myhome.ge/en/real-estate/rent/apartment/tbilisi/{myhome_slug}/?{q}"
    q = urllib.parse.urlencode({"cityIdList":"95","subdistrictIds":ss_id,"currencyId":"1","page":str(page),"advancedSearch":json.dumps({"individualEntityOnly":True},separators=(",",":"))})
    return f"https://home.ss.ge/en/real-estate/l/Flat/For-Rent?{q}"


def parse_date(text: str) -> datetime | None:
    now = datetime.now(TZ); s = " ".join((text or "").split()).lower(); out=[]
    for pat, unit in [
        (r"(\d+)\s*(?:minute|minutes|min|mins)\s+ago","minutes"),(r"(\d+)\s*(?:hour|hours|hr|hrs)\s+ago","hours"),(r"(\d+)\s*(?:day|days)\s+ago","days"),
        (r"(\d+)\s*(?:წუთი|წუთის)\s*წინ","minutes"),(r"(\d+)\s*(?:საათი|საათის)\s*წინ","hours"),(r"(\d+)\s*(?:დღე|დღის)\s*წინ","days"),
        (r"(\d+)\s*(?:минута|минуты|минут)\s*назад","minutes"),(r"(\d+)\s*(?:час|часа|часов)\s*назад","hours"),(r"(\d+)\s*(?:день|дня|дней)\s*назад","days")]:
        for m in re.finditer(pat,s,re.I): out.append(now-timedelta(**{unit:int(m.group(1))}))
    for m in re.finditer(r"(?:today|დღეს|сегодня)\D{0,12}(\d{1,2}):(\d{2})",s,re.I):
        try: out.append(now.replace(hour=int(m.group(1)),minute=int(m.group(2)),second=0,microsecond=0))
        except ValueError: pass
    yday=now-timedelta(days=1)
    for m in re.finditer(r"(?:yesterday|გუშინ|вчера)\D{0,12}(\d{1,2}):(\d{2})",s,re.I):
        try: out.append(yday.replace(hour=int(m.group(1)),minute=int(m.group(2)),second=0,microsecond=0))
        except ValueError: pass
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\s*[-,]\s*(\d{1,2}):(\d{2})\b",s):
        d,mo,y,h,mi=map(int,m.groups()); y=y+2000 if y<100 else y
        try: out.append(datetime(y,mo,d,h,mi,tzinfo=TZ))
        except ValueError: pass
    for m in re.finditer(r"\b(\d{1,2})\s+([A-Za-zА-Яа-яЁёႠ-ჿ]{3,14})(?:\s+(\d{2,4}))?(?:[,\s]+(\d{1,2}):(\d{2}))?",s,re.I):
        d=int(m.group(1)); mw=m.group(2).lower().strip("."); mo=MONTHS.get(mw)
        if mo is None:
            for k,v in MONTHS.items():
                if mw.startswith(k) or k.startswith(mw): mo=v; break
        if mo is None: continue
        y=int(m.group(3)) if m.group(3) else now.year; y=y+2000 if y<100 else y
        h=int(m.group(4) or 0); mi=int(m.group(5) or 0)
        try:
            dt=datetime(y,mo,d,h,mi,tzinfo=TZ)
            if not m.group(3) and dt>now+timedelta(days=2): dt=dt.replace(year=y-1)
            out.append(dt)
        except ValueError: pass
    ok=[x for x in out if now-timedelta(days=365)<=x<=now+timedelta(hours=2)]
    return max(ok) if ok else None


async def collect_cards(page: Any, site: str) -> list[dict[str,str]]:
    return await page.evaluate(r'''(site)=>{const clean=v=>(v||'').replace(/\s+/g,' ').trim();const out=[],seen=new Set();
const valid=h=>site==='SS.ge'?/\/real-estate\/(?!l\/)[^?#]*-\d{6,10}(?:[/?#]|$)/i.test(h):(/\/(?:[a-z]{2}\/)?pr\/\d{6,10}(?:\/|$)/i.test(h)||/\/(?:[a-z]{2}\/)?real-estate\/\d{6,10}\//i.test(h)||/\/(?:[a-z]{2}\/)?real-estate\/[^?#]*-\d{6,10}(?:\/|$)/i.test(h)||/\/(?:[a-z]{2}\/)?nedvizhimost\/[^?#]*-\d{6,10}(?:\/|$)/i.test(h));
for(const a of document.querySelectorAll('a[href]')){const href=(a.href||'').split('#')[0];if(!valid(href)||seen.has(href))continue;let n=a,card=a,text=clean(a.innerText||a.title||'');for(let i=0;i<8&&n;i++){const t=clean(n.innerText||'');if(t.length>=15&&t.length<=1800&&/(?:m²|m2|room|ოთახ|комнат)/i.test(t)){card=n;text=t;break;}n=n.parentElement;}let image='';for(const img of [...card.querySelectorAll('img'),...a.querySelectorAll('img')]){for(const v of [img.currentSrc,img.src,img.getAttribute('data-src'),img.getAttribute('data-lazy-src'),img.getAttribute('data-original')]){if(v&&/^https?:\/\//i.test(v)&&!/logo|icon|avatar|banner|advert|promo|favicon/i.test(v)){image=v;break;}}if(image)break;}seen.add(href);out.push({href,text,image});}return out;}''',site)


def myhome_role(raw: str) -> str | None:
    for pat in [r"\n\s*(Owner|Agent)\s*\n\s*All statements",r"All statements[^\n]*\n(?:[^\n]*\n){0,3}\s*(Owner|Agent)\s*(?:\n|$)"]:
        m=re.search(pat,raw or "",re.I)
        if m:return m.group(1).lower()
    return None



def ss_clear_agency(raw: str) -> bool:
    """Reject only strong agency signatures; owner-like text is not rejected."""
    s = raw or ""
    strong = (
        r"\breal estate agency\b",
        r"\bagency statement\b",
        r"\bагентство недвижимости\b",
        r"\bუძრავი ქონების სააგენტო\b",
        r"\n[^\n]{1,60}\bAgency\s*\n\s*Languages\b",
    )
    return any(re.search(pat, s, re.I) for pat in strong)


async def capture_myhome_photo(page: Any, preferred_url: str = "") -> bytes | None:
    """
    MyHome-specific photo capture.

    MyHome can serve listing photos from CDN hosts that check_once.py does not
    whitelist. We therefore collect the real image URLs from the detail page
    and fetch them through Playwright using the same browser session/referrer.
    If direct fetching is unavailable, we screenshot the largest visible
    property image element. Logos/avatars/icons are excluded.
    """
    candidates = await page.evaluate(
        r"""
        () => {
          const abs = (value) => {
            if (!value) return '';
            try { return new URL(value, document.baseURI).href; }
            catch (_) { return ''; }
          };

          const blocked =
            /logo|icon|avatar|profile|owner|badge|banner|advert|promo|favicon|sprite|flag|googleplay|appstore|qr/i;

          const out = [];
          const seen = new Set();

          const add = (value, score, index = null, hint = '') => {
            const url = abs(value);
            if (!url || seen.has(url) || blocked.test(`${url} ${hint || ''}`)) return;
            if (!/^https?:\/\//i.test(url)) return;
            seen.add(url);
            out.push({url, score, index});
          };

          for (const selector of [
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
            'meta[property="twitter:image"]'
          ]) {
            const node = document.querySelector(selector);
            if (node?.content) add(node.content, 5000000, null, selector);
          }

          Array.from(document.images).forEach((img, index) => {
            const rect = img.getBoundingClientRect();
            const w = Math.max(img.naturalWidth || 0, rect.width || 0);
            const h = Math.max(img.naturalHeight || 0, rect.height || 0);
            const hint = `${img.alt || ''} ${img.className || ''} ${img.id || ''}`;

            if (w < 250 || h < 160) return;

            const area = Math.min(w * h, 3000000);
            let score = area;

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

            content_type = (response.headers.get("content-type") or "").lower()
            if not content_type.startswith("image/"):
                continue

            photo = await response.body()
            if 2_000 <= len(photo) <= 9_500_000:
                print(f"MYHOME_PHOTO direct_ok bytes={len(photo)} url={image_url[:160]}")
                return photo
        except Exception as exc:
            print(f"MYHOME_PHOTO direct_fail {type(exc).__name__}: {image_url[:160]}")

    # Fallback: screenshot the largest visible image element itself.
    for item in candidates:
        index = item.get("index")
        if index is None:
            continue
        try:
            locator = page.locator("img").nth(int(index))
            if not await locator.is_visible():
                continue
            box = await locator.bounding_box()
            if not box or box["width"] < 250 or box["height"] < 160:
                continue
            photo = await locator.screenshot(
                type="jpeg",
                quality=88,
                animations="disabled",
                timeout=15_000,
            )
            if 2_000 <= len(photo) <= 9_500_000:
                print(f"MYHOME_PHOTO element_ok bytes={len(photo)} index={index}")
                return photo
        except Exception:
            continue

    print("MYHOME_PHOTO no_real_photo_found")
    return None


async def verify(context: Any, c: dict[str,Any], label: str, aliases:set[str], rate:float) -> dict[str,Any] | None:
    site,url=c["site"],c["url"]
    if not exact_district(site,url,aliases) or room_from_url(site,url) not in {1,2,3}: return None
    p=await context.new_page()
    try:
        await p.goto(url,wait_until="domcontentloaded",timeout=70000); await p.wait_for_timeout(1500)
        raw=await p.locator("body").inner_text(timeout=15000); body=check_once.normalize_text(raw)
        if site=="SS.ge":
            if not re.search(r"\b[123]\s*room\s+Flat\s+For\s+Rent\b",body,re.I): return None
            if ss_clear_agency(raw): return None
        else:
            if not re.search(r"\b[123]\s*room\s+apartment\s+for\s+rent\b",body,re.I): return None
            role=myhome_role(raw)
            if role!="owner": return None
        pub=parse_date(c.get("text","")+"\n"+raw)
        if pub is not None and datetime.now(TZ)-pub>timedelta(hours=FRESH_HOURS): return None
        if pub is None and c["page"]>2: return None
        lid=listing_id(site,url)
        if not lid:return None
        text=body if len(body)>len(c.get("text",'')) else c.get("text",'')
        item={"source_key":"manual_myhome" if site=="MyHome.ge" else "manual_ss","site":site,"deal":"rent","listing_id":lid,"url":url,"rooms":room_from_url(site,url),"price":check_once.extract_price(text,rate),"area":check_once.extract_area(text),"location":label,"address":check_once.extract_address(text,label),"image":c.get("image",''),"summary":c.get("text",'')[:700],"manual_search":True,"published_at":pub,"page_number":c["page"],"discovery_order":c["order"]}
        if site=="MyHome.ge":
            myhome_photo=await capture_myhome_photo(p,item["image"])
            item["photo_bytes"]=myhome_photo or await check_once.capture_listing_photo(p,item["image"])
        else:
            item["photo_bytes"]=await check_once.capture_listing_photo(p,item["image"])
        return item
    except Exception as e:
        print(f"VERIFY_FAIL {site} {url} {type(e).__name__}: {e}"); return None
    finally: await p.close()


async def source_pool(context: Any, site:str, label:str, myhome_slug:str, ss_id:str, aliases:set[str], rate:float) -> list[dict[str,Any]]:
    max_pages=12 if site=="MyHome.ge" else 10; seen={}; order=0
    for pn in range(1,max_pages+1):
        p=await context.new_page()
        try:
            u=search_url(site,myhome_slug,ss_id,pn); print(f"SEARCH {site} page={pn}")
            await p.goto(u,wait_until="domcontentloaded",timeout=90000); await p.wait_for_timeout(3500)
            for _ in range(4): await p.mouse.wheel(0,1800); await p.wait_for_timeout(500)
            cards=await collect_cards(p,site); exact=0
            for x in cards:
                url=x.get("href",'')
                if room_from_url(site,url) not in {1,2,3} or not exact_district(site,url,aliases): continue
                lid=listing_id(site,url)
                if not lid: continue
                exact+=1; order+=1
                seen.setdefault(lid,{"site":site,"url":url,"text":x.get("text",''),"image":x.get("image",''),"page":pn,"order":order})
            print(f"PAGE {site} {pn}: cards={len(cards)} exact={exact} unique={len(seen)}")
            if len(seen)>=50: break
        except Exception as e: print(f"SEARCH_FAIL {site} page={pn}: {type(e).__name__}: {e}")
        finally: await p.close()
    verified=[]
    for c in list(seen.values())[:50]:
        item=await verify(context,c,label,aliases,rate)
        if item: verified.append(item)
        if len(verified)>=24: break
    print(f"VERIFIED {site}: raw_exact={len(seen)} accepted={len(verified)}")
    return verified


def sort_key(x:dict[str,Any]):
    p=x.get("published_at"); ts=p.timestamp() if isinstance(p,datetime) else 0
    return (ts,-x.get("page_number",99),-x.get("discovery_order",999999),int(x.get("listing_id",0)))


def balance(m:list[dict[str,Any]],s:list[dict[str,Any]])->list[dict[str,Any]]:
    m=sorted(m,key=sort_key,reverse=True); s=sorted(s,key=sort_key,reverse=True)
    take=min(15,LIMIT//2); out=m[:take]+s[:take]; rest=sorted(m[take:]+s[take:],key=sort_key,reverse=True)
    out+=rest[:max(0,LIMIT-len(out))]; out=sorted(out,key=sort_key,reverse=True)[:LIMIT]
    print(json.dumps({"sent":len(out),"myhome":sum(x['site']=='MyHome.ge' for x in out),"ss":sum(x['site']=='SS.ge' for x in out),"fresh_hours":FRESH_HOURS},ensure_ascii=False))
    return out


async def run()->int:
    if DISTRICT not in DISTRICTS: print(f"Unknown district {DISTRICT}"); return 2
    label,myhome_slug,ss_id,aliases=DISTRICTS[DISTRICT]; rate=check_once.get_usd_rate()
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled"])
        ctx=await browser.new_context(locale="en-US",timezone_id="Asia/Tbilisi",viewport={"width":1440,"height":1200},user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        m=await source_pool(ctx,"MyHome.ge",label,myhome_slug,ss_id,aliases,rate)
        s=await source_pool(ctx,"SS.ge",label,myhome_slug,ss_id,aliases,rate)
        out=balance(m,s); await ctx.close(); await browser.close()
    if not out:
        check_once.send_telegram("ℹ️ По выбранному району новых объявлений сейчас не найдено."); return 0
    for item in out: check_once.send_listing(item)
    print(f"DONE district={DISTRICT} sent={len(out)}"); return 0


if __name__=="__main__": raise SystemExit(asyncio.run(run()))
