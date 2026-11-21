#!/usr/bin/env python3
"""Obavijest o slobodnim padel terminima u Padel Embassyju (Playtomic).

Program otvori javnu stranicu kluba u pravom pregledniku (Edge ili Chrome na
tvom računalu), prebaci tablicu na traženi dan, pročita slobodne termine koje
stranica prikaže i pošalje ti obavijest na mobitel preko aplikacije ntfy.
Ništa ne rezervira i ne zove Playtomic API izravno: čita samo ono što stranica
sama učita, kao da je otvoriš ti.

Primjeri:
    python padel_obavijest.py --test-notify          # probna obavijest
    python padel_obavijest.py --show --debug         # pokaži preglednik i spremi dijagnostiku
    python padel_obavijest.py --any --days-ahead 2   # bilo koji termin za 2 dana (test)
    python padel_obavijest.py --start-at 08:00       # pričekaj 8:00 pa javi termine za 7 dana
"""

from __future__ import annotations

import sys

if sys.stdout is None:  # pythonw.exe (Task Scheduler): bez konzole – sve odmah u zapis.txt
    import os as _os
    _log = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "zapis.txt"),
                "a", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = sys.stderr = _log
    print("\n--- pokrenuto bez konzole:", " ".join(sys.argv))

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# --- postavke -----------------------------------------------------------------
CLUB_URL = "https://playtomic.com/clubs/padel-embassy"
TENANT_ID = "2ea46d91-f7ed-4e4a-aa5c-392ee5995ad9"
# link u obavijesti: otvara klub u Playtomic aplikaciji (može se promijeniti u postavke.json pod "link")
APP_LINK = f"https://playtomic.com/tenant/{TENANT_ID}"
# raspon početka termina po danu u tjednu (0 = pon ... 6 = ned); dan koji nije naveden se preskače
WORKDAY = ("17:00", "21:00")
WEEKEND = ("09:00", "12:00")
WINDOWS = {0: WORKDAY, 1: WORKDAY, 2: WORKDAY, 3: WORKDAY, 4: WORKDAY, 5: WEEKEND, 6: WEEKEND}
DURATION = 90               # minuta
DAYS_AHEAD = 7              # termini se otvaraju 7 dana unaprijed

TZ = ZoneInfo("Europe/Zagreb")
HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "postavke.json"
STATE_FILE = HERE / "stanje.json"     # termini javljeni u prethodnoj provjeri
LOCK_FILE = HERE / "provjera.lock"    # sprječava dvije provjere istovremeno
NIGHT = (23, 7)                       # noću (23–7 h) se ne provjerava
ERROR_PAUSE_HOURS = 2                 # greške javljaj najviše jednom u ovoliko sati
DEBUG_DIR = HERE / "debug"
DAY_NAMES = ["pon", "uto", "sri", "čet", "pet", "sub", "ned"]


@dataclass
class Slot:
    court: str
    start: str      # "HH:MM", zagrebačko vrijeme
    duration: int
    price: str
    resource_id: str = ""
    start_utc: datetime | None = None


def booking_url(slot: Slot) -> str:
    """Link koji otvara plaćanje točno ovog termina (u aplikaciji ako je instalirana, inače web)."""
    return "https://app.playtomic.com/payments?" + urlencode({
        "type": "CUSTOMER_MATCH", "tenant_id": TENANT_ID, "resource_id": slot.resource_id,
        "start": slot.start_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "duration": str(slot.duration), "sport_id": "PADEL",
    })


# --- obavijesti ---------------------------------------------------------------
def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    return {}


def notify(topic: str | None, title: str, message: str, high: bool = False,
           buttons: list[tuple[str, str]] | None = None) -> None:
    """buttons: do 3 gumba (natpis, link) ispod obavijesti; bez njih gumb otvara klub."""
    link = load_config().get("link", APP_LINK)
    buttons = (buttons or [])[:3] or [("Otvori Playtomic", link)]
    actions = "; ".join(f"view, {label.replace(',', ' ')}, {url}" for label, url in buttons)
    print(f"\n=== {title} ===\n{message}\n")
    if not topic:
        print("(ntfy topic nije postavljen u postavke.json – obavijest nije poslana)")
        return
    r = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Tags": "tennis",
            "Priority": "high" if high else "default",
            "Click": link,
            "Actions": actions.encode("utf-8"),
        },
        timeout=15,
    )
    r.raise_for_status()
    print("Obavijest poslana.")


# --- čitanje podataka sa stranice ------------------------------------------------
def courts_from_html(html: str) -> dict[str, tuple[str, bool]]:
    """{resource_id: (naziv, je_li_double)} iz podataka ugrađenih u stranicu."""
    q = r'\\?"'  # navodnik, možda escapean unutar Next.js podataka
    pattern = (
        rf'{q}resourceId{q}:{q}([0-9a-f-]{{36}}){q},{q}name{q}:{q}(.*?){q},'
        rf'{q}sport{q}:{q}PADEL{q},{q}features{q}:\[(.*?)\]'
    )
    courts = {}
    for rid, name, features in re.findall(pattern, html):
        courts[rid] = (name.replace("\\/", "/"), "double" in features.lower())
    return courts


def find_availability(obj) -> list[dict]:
    """Iz bilo kojeg JSON odgovora izvuci zapise oblika {resource_id, start_date, slots:[...]}."""
    found = []
    if isinstance(obj, dict):
        rid = obj.get("resource_id") or obj.get("resourceId")
        if rid and isinstance(obj.get("slots"), list):
            found.append(obj)
        else:
            for v in obj.values():
                found += find_availability(v)
    elif isinstance(obj, list):
        for v in obj:
            found += find_availability(v)
    return found


def local_start(start_date: str, start_time: str) -> datetime:
    """Playtomic šalje vrijeme u UTC-u; pretvori u zagrebačko (zimi +1, ljeti +2)."""
    utc = datetime.fromisoformat(f"{start_date[:10]}T{start_time[:8]}").replace(tzinfo=ZoneInfo("UTC"))
    return utc.astimezone(TZ)


def slots_for_day(entries: list[dict], courts: dict, day: date, any_slot: bool) -> list[Slot]:
    lo, hi = ("00:00", "23:59") if any_slot else WINDOWS[day.weekday()]
    out = {}
    for e in entries:
        rid = e.get("resource_id") or e.get("resourceId")
        name, is_double = courts.get(rid, (rid[:8], True))
        if not is_double:
            continue
        for s in e["slots"]:
            try:
                start_dt = local_start(str(e.get("start_date", "")), str(s.get("start_time", "")))
            except ValueError:
                continue
            start = start_dt.strftime("%H:%M")
            dur = int(s.get("duration", 0))
            if start_dt.date() != day or dur != DURATION or not (lo <= start <= hi):
                continue
            out[(name, start)] = Slot(name, start, dur, str(s.get("price", "")), rid, start_dt)
    return sorted(out.values(), key=lambda s: (s.start, s.court))


# --- preglednik --------------------------------------------------------------------
def launch(p, show: bool, headless: bool):
    # Playtomic skrivenom (headless) pregledniku ne prikazuje termine, pa se otvara
    # normalan prozor; bez --show se postavi izvan ekrana da ne smeta.
    args = [] if show or headless else ["--window-position=-3000,-3000"]
    last = None
    for channel in ("msedge", "chrome", None):
        try:
            kwargs = {"headless": headless, "args": args}
            if channel:
                kwargs["channel"] = channel
            browser = p.chromium.launch(**kwargs)
            print(f"Preglednik: {channel or 'chromium (playwright)'}")
            return browser
        except Exception as exc:  # preglednik nije instaliran
            last = exc
    raise SystemExit(f"Ne mogu pokrenuti preglednik: {last}")


DATE_RE_JS = r"/[^\s,\d]{2,12},\s*\d{1,2}\.?\s*[^\s\d]{2,12}/"

DATE_LABEL_JS = r"""() => {
  // najmanji element čiji tekst sadrži datum iznad tablice, npr. "sub, 21. stu" ili "Sat, 21 Nov"
  const re = """ + DATE_RE_JS + r""";
  let best = null;
  for (const el of document.querySelectorAll('body *')) {
    if (!el.offsetWidth) continue;
    const t = (el.innerText || '').trim();
    if (t.length > 40 || !re.test(t)) continue;
    if (!best || best.contains(el)) best = el;
  }
  if (!best) return null;
  // strelica za sljedeći dan = prvi gumb samo s ikonom (bez teksta) iza natpisa
  // referentna točka je sam tekst s brojem dana (ne cijeli blok, koji može sadržavati i strelice)
  const walker = document.createTreeWalker(best, NodeFilter.SHOW_TEXT);
  let ref = best;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) if (/\d/.test(n.textContent)) { ref = n; break; }
  const iconOnly = b => b.offsetWidth > 0 && !/[\p{L}\d]/u.test(b.innerText || '') && !b.contains(ref);
  document.querySelectorAll('[data-padel-next]').forEach(b => b.removeAttribute('data-padel-next'));
  let box = best.parentElement;
  for (let i = 0; i < 5 && box; i++, box = box.parentElement) {
    const after = [...box.querySelectorAll('button,[role=button],a')].filter(iconOnly)
      .filter(b => ref.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    if (after.length) {
      after[0].setAttribute('data-padel-next', '1');
      break;
    }
  }
  return best.innerText.trim().match(re)[0];
}"""

DATE_AREA_JS = r"""() => {
  const re = """ + DATE_RE_JS + r""";
  let best = null;
  for (const el of document.querySelectorAll('body *')) {
    const t = (el.innerText || '').trim();
    if (t.length <= 40 && re.test(t) && (!best || best.contains(el))) best = el;
  }
  let box = best;
  for (let i = 0; i < 3 && box && box.parentElement; i++) box = box.parentElement;
  return box ? box.outerHTML.slice(0, 3000) : 'datum nije pronađen';
}"""


def accept_cookies(page) -> None:
    for label in ("Accept all", "Accept", "Prihvati sve", "Prihvati", "Allow all", "Agree"):
        btn = page.get_by_role("button", name=re.compile(rf"^\s*{label}", re.I))
        try:
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


def click_next_day(page) -> str | None:
    """Klikni strelicu za sljedeći dan; vrati natpis datuma nakon klika."""
    if page.evaluate(DATE_LABEL_JS) is None or not page.locator("[data-padel-next='1']").count():
        return None
    page.locator("[data-padel-next='1']").first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(800)
    return page.evaluate(DATE_LABEL_JS)


def read_page(target: date, show: bool, debug: bool, headless: bool = False) -> tuple[list[dict], dict, str]:
    from playwright.sync_api import sync_playwright

    responses: list[tuple[str, object]] = []

    def on_response(resp):
        if debug and "availability" in resp.url:
            print(f"  [{resp.status}] {resp.url[:120]}")
        if "json" not in resp.headers.get("content-type", ""):
            return
        try:
            responses.append((resp.url, resp.json()))
        except Exception:
            pass

    with sync_playwright() as p:
        browser = launch(p, show, headless)
        ctx = browser.new_context(locale="hr-HR", timezone_id="Europe/Zagreb",
                                  viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(CLUB_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        accept_cookies(page)
        label = page.evaluate(DATE_LABEL_JS)
        print(f"Prikazani dan: {label}")

        clicks = (target - datetime.now(TZ).date()).days
        for _ in range(max(clicks, 0)):
            label = click_next_day(page)
            if label is None:
                print("Ne mogu pronaći strelicu za sljedeći dan.")
                if debug:
                    print("--- HTML oko datuma ---\n" + page.evaluate(DATE_AREA_JS) + "\n---")
                break
        print(f"Nakon pomicanja ({clicks}x): {label}")

        html = page.content()
        if debug:
            DEBUG_DIR.mkdir(exist_ok=True)
            page.screenshot(path=str(DEBUG_DIR / "stranica.png"), full_page=True)
            (DEBUG_DIR / "stranica.html").write_text(html, encoding="utf-8")
            (DEBUG_DIR / "odgovori.json").write_text(
                json.dumps([{"url": u, "data": d} for u, d in responses], ensure_ascii=False,
                           indent=1)[:5_000_000], encoding="utf-8")
            print(f"Dijagnostika spremljena u {DEBUG_DIR}")
        browser.close()

    entries = []
    for url, data in responses:
        found = find_availability(data)
        entries += found
        if debug:
            days = sorted({str(e.get("start_date", "?"))[:10] for e in found})
            print(f"  JSON {url[:110]} -> termina: {len(found)} {days if found else ''}")
    return entries, courts_from_html(html), label or ""


# --- glavni dio ------------------------------------------------------------------------
def wait_until(hhmm: str) -> None:
    h, m = map(int, hhmm.split(":"))
    target = datetime.now(TZ).replace(hour=h, minute=m, second=5, microsecond=0)
    while (left := (target - datetime.now(TZ)).total_seconds()) > 0:
        print(f"Čekam do {hhmm} ({left:.0f} s)...", end="\r")
        time.sleep(min(left, 20))
    print()


def fmt_day(d: date) -> str:
    return f"{DAY_NAMES[d.weekday()]} {d.strftime('%d.%m.')}"


def format_day(d: date, slots: list[Slot], buttons: list | None = None) -> list[str]:
    """Svaki teren u svom retku, ispod njega link na plaćanje točno tog terena i termina.
    Ako je zadan popis buttons, dodaje u njega (natpis, link) za gumbe u obavijesti."""
    lines = [f"📅 {fmt_day(d)}:"]
    for s in sorted(slots, key=lambda s: (s.start, s.court)):
        court = s.court.split(" ///")[0]
        url = booking_url(s)
        lines.append(f"  {s.start} – {court}")
        lines.append(f"  👉 {url}")
        if buttons is not None:
            buttons.append((f"{fmt_day(d)} {s.start} {court}", url))
    return lines


# --- praćenje svakih 10 minuta -------------------------------------------------------
def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def acquire_lock() -> bool:
    for _ in range(2):
        try:
            os.close(os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            # zaostala brava od srušene provjere
            if time.time() - LOCK_FILE.stat().st_mtime < 15 * 60:
                return False
            LOCK_FILE.unlink(missing_ok=True)
    return False


def notify_error(topic: str | None, state: dict, message: str) -> None:
    last = state.get("last_error_notified", 0)
    if time.time() - last >= ERROR_PAUSE_HOURS * 3600:
        notify(topic, "❌ Padel – greška", message, high=True)
        state["last_error_notified"] = time.time()
    else:
        print(f"Greška (obavijest već poslana nedavno): {message}")
    save_state(state)


def watch(args, topic: str | None) -> int:
    now = datetime.now(TZ)
    if not args.start_at and (now.hour >= NIGHT[0] or now.hour < NIGHT[1]):
        print("Noć je – preskačem provjeru.")
        return 0
    if not acquire_lock():
        print("Druga provjera je upravo u tijeku – preskačem.")
        return 0
    try:
        return _watch(args, topic)
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def _watch(args, topic: str | None) -> int:
    if args.start_at:
        wait_until(args.start_at)
    now = datetime.now(TZ)
    today = now.date()
    last = today + timedelta(days=args.days_ahead)
    days = [today + timedelta(days=i) for i in range(args.days_ahead + 1)]
    days = [d for d in days if args.any or d.weekday() in WINDOWS]
    state = load_state()

    deadline = time.monotonic() + args.retry_minutes * 60
    try:
        while True:
            entries, courts, label = read_page(last, args.show, args.debug, args.headless)
            loaded = {str(e.get("start_date", ""))[:10] for e in entries}
            have = [d for d in days if d.isoformat() in loaded]
            # u 8:00 pričekaj da se otvori zadnji dan
            if not args.start_at or (days and days[-1] in have) or time.monotonic() >= deadline:
                break
            print("Novi dan još nije otvoren – pokušavam ponovno za 20 s.")
            time.sleep(20)
    except Exception as exc:
        notify_error(topic, state, f"Program nije uspio pročitati stranicu: {exc}")
        raise

    if not have:
        notify_error(topic, state, f"Nisam uspio pročitati termine (prikazano: {label}). "
                                   "Pokreni s --show --debug.")
        return 1

    prev = state.get("slots", {})
    current = {k: v for k, v in prev.items() if k >= today.isoformat()}
    lines = []
    buttons: list[tuple[str, str]] = []
    for d in have:
        slots = slots_for_day(entries, courts, d, args.any)
        if d == today:  # termini koji su već počeli
            slots = [s for s in slots if s.start > now.strftime("%H:%M")]
        old = set(prev.get(d.isoformat(), []))
        new = [s for s in slots if f"{s.start}|{s.court}" not in old]
        current[d.isoformat()] = sorted(f"{s.start}|{s.court}" for s in slots)
        print(f"{fmt_day(d)}: slobodno {len(slots)}, novo {len(new)}")
        if new:
            lines += format_day(d, new, buttons)
    state["slots"] = current
    state.pop("last_error_notified", None)  # sve radi – sljedeća greška se opet javlja odmah
    save_state(state)

    missing = [fmt_day(d) for d in days if d not in have]
    if missing:
        print(f"Nema podataka za: {', '.join(missing)}")
    if lines:
        notify(topic, f"🆕 Padel – novi slobodni termini ({DURATION} min)", "\n".join(lines),
               buttons=buttons)
    else:
        print("Nema novih termina.")
    return 0


def start_log(path: Path) -> None:
    """Preusmjeri ispis u datoteku (pythonw.exe iz Task Schedulera nema konzolu)."""
    if not path.is_absolute():  # Task Scheduler pokreće program iz drugog foldera
        path = HERE / path
    if path.exists() and path.stat().st_size > 1_000_000:  # drži zapis malim
        tail = path.read_bytes()[-300_000:]
        path.write_bytes(tail[tail.find(b"\n") + 1:])
    f = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = sys.stderr = f
    print(f"\n--- {datetime.now(TZ):%Y-%m-%d %H:%M:%S}  {' '.join(sys.argv[1:])}")


def main() -> int:
    # Windows konzola/datoteka inače ne zna ispisati emoji i hrvatska slova
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pythonw.exe nema konzolu (stdout je None)
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days-ahead", type=int, default=DAYS_AHEAD, help="za koliko dana unaprijed")
    ap.add_argument("--any", action="store_true", help="bilo koji dan i sat (za testiranje)")
    ap.add_argument("--start-at", help="pričekaj do HH:MM pa kreni (npr. 08:00)")
    ap.add_argument("--retry-minutes", type=int, default=5,
                    help="ako termini još nisu otvoreni, pokušavaj ovoliko minuta")
    ap.add_argument("--show", action="store_true", help="prikaži prozor preglednika")
    ap.add_argument("--headless", action="store_true",
                    help="skriveni preglednik (Playtomic mu možda ne prikaže termine)")
    ap.add_argument("--debug", action="store_true", help="spremi screenshot i podatke u mapu debug")
    ap.add_argument("--log", help="ispis dodaj u ovu datoteku (za pokretanje iz Task Schedulera)")
    ap.add_argument("--watch", action="store_true",
                    help="provjeri sve dane do --days-ahead i javi samo NOVE termine")
    ap.add_argument("--test-notify", action="store_true", help="pošalji probnu obavijest i izađi")
    args = ap.parse_args()
    if args.log:
        start_log(Path(args.log))

    topic = load_config().get("ntfy_topic")
    if args.test_notify:
        notify(topic, "🎾 Padel – probna obavijest", "Obavijesti rade!")
        return 0
    if args.watch:
        return watch(args, topic)

    if args.start_at:
        wait_until(args.start_at)
    target = datetime.now(TZ).date() + timedelta(days=args.days_ahead)
    if not args.any and target.weekday() not in WINDOWS:
        print(f"{fmt_day(target)} se ne prati – ništa za javiti.")
        return 0

    deadline = time.monotonic() + args.retry_minutes * 60
    try:
        while True:
            entries, courts, label = read_page(target, args.show, args.debug, args.headless)
            day_entries = [e for e in entries if str(e.get("start_date", ""))[:10] == target.isoformat()]
            if day_entries or time.monotonic() >= deadline:
                break
            print("Termini za taj dan još nisu učitani/otvoreni – pokušavam ponovno za 20 s.")
            time.sleep(20)
    except Exception as exc:
        notify(topic, "❌ Padel – greška", f"Program nije uspio pročitati stranicu: {exc}", high=True)
        raise

    print(f"Tereni: {', '.join(n + (' (double)' if d else '') for n, d in courts.values()) or '?'}")
    print(f"Zapisa o terminima: {len(entries)}, za {target}: {len(day_entries)}")

    if not day_entries:
        notify(topic, "❌ Padel – nema podataka",
               f"Nisam uspio pročitati termine za {fmt_day(target)} (prikazano: {label}). "
               "Pokreni s --show --debug i pošalji mapu debug.", high=True)
        return 1

    slots = slots_for_day(entries, courts, target, args.any)
    if not slots:
        rng = "" if args.any else ", početak {}–{}".format(*WINDOWS[target.weekday()])
        notify(topic, "🎾 Padel – nema slobodnih termina",
               f"{fmt_day(target)}: nema slobodnog double terena ({DURATION} min{rng}).")
        return 0

    buttons: list[tuple[str, str]] = []
    lines = format_day(target, slots, buttons)
    notify(topic, f"🎾 Padel – slobodni termini ({DURATION} min)", "\n".join(lines), buttons=buttons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
