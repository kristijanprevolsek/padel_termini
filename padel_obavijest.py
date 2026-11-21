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

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# --- postavke -----------------------------------------------------------------
CLUB_URL = "https://playtomic.com/clubs/padel-embassy"
DAYS = {0, 1, 2}            # pon, uto, sri
EARLIEST = "19:00"          # najraniji početak
LATEST = "22:00"            # najkasniji početak
DURATION = 90               # minuta
DAYS_AHEAD = 7              # termini se otvaraju 7 dana unaprijed

TZ = ZoneInfo("Europe/Zagreb")
HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "postavke.json"
DEBUG_DIR = HERE / "debug"
DAY_NAMES = ["pon", "uto", "sri", "čet", "pet", "sub", "ned"]

NEXT_BUTTON_NAMES = re.compile(r"next|sljede|naprijed|siguiente|weiter|suivant|forward", re.I)


@dataclass
class Slot:
    court: str
    start: str      # "HH:MM"
    duration: int
    price: str


# --- obavijesti ---------------------------------------------------------------
def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    return {}


def notify(topic: str | None, title: str, message: str, high: bool = False) -> None:
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
            "Click": CLUB_URL,
            "Actions": f"view, Otvori klub, {CLUB_URL}",
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


def slots_for_day(entries: list[dict], courts: dict, day: date, any_slot: bool) -> list[Slot]:
    lo, hi = ("00:00", "23:59") if any_slot else (EARLIEST, LATEST)
    out = {}
    for e in entries:
        rid = e.get("resource_id") or e.get("resourceId")
        if str(e.get("start_date", ""))[:10] != day.isoformat():
            continue
        name, is_double = courts.get(rid, (rid[:8], True))
        if not is_double:
            continue
        for s in e["slots"]:
            start = str(s.get("start_time", ""))[:5]
            dur = int(s.get("duration", 0))
            if dur != DURATION or not (lo <= start <= hi):
                continue
            out[(name, start)] = Slot(name, start, dur, str(s.get("price", "")))
    return sorted(out.values(), key=lambda s: (s.start, s.court))


# --- preglednik --------------------------------------------------------------------
def launch(p, show: bool):
    last = None
    for channel in ("msedge", "chrome", None):
        try:
            kwargs = {"headless": not show}
            if channel:
                kwargs["channel"] = channel
            browser = p.chromium.launch(**kwargs)
            print(f"Preglednik: {channel or 'chromium (playwright)'}")
            return browser
        except Exception as exc:  # preglednik nije instaliran
            last = exc
    raise SystemExit(f"Ne mogu pokrenuti preglednik: {last}")


DATE_LABEL_JS = r"""() => {
  // pronađi kratki natpis s datumom pored strelica (npr. "ned, 22. stu" ili "Sun, 22 Nov")
  const els = [...document.querySelectorAll('span,div,p,button,h2,h3')];
  for (const el of els) {
    const t = (el.innerText || '').trim();
    if (t.length < 5 || t.length > 25 || el.children.length > 1) continue;
    if (!/\d/.test(t) || !/,/.test(t)) continue;
    let box = el.parentElement;
    for (let i = 0; i < 3 && box; i++, box = box.parentElement) {
      const btns = [...box.querySelectorAll('button')].filter(b => b.offsetWidth > 0);
      if (btns.length >= 2) {
        btns.forEach(b => b.removeAttribute('data-padel-next'));
        btns[btns.length - 1].setAttribute('data-padel-next', '1');
        return t;
      }
    }
  }
  return null;
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
    btn = page.get_by_role("button", name=NEXT_BUTTON_NAMES)
    if btn.count() and btn.first.is_visible():
        btn.first.click()
    else:
        if page.evaluate(DATE_LABEL_JS) is None:
            return None
        page.locator("[data-padel-next='1']").first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(800)
    return page.evaluate(DATE_LABEL_JS)


def read_page(target: date, show: bool, debug: bool) -> tuple[list[dict], dict, str]:
    from playwright.sync_api import sync_playwright

    responses: list[tuple[str, object]] = []

    def on_response(resp):
        if "json" not in resp.headers.get("content-type", ""):
            return
        try:
            responses.append((resp.url, resp.json()))
        except Exception:
            pass

    with sync_playwright() as p:
        browser = launch(p, show)
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
    for _, data in responses:
        entries += find_availability(data)
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


def main() -> int:
    # Windows konzola/datoteka inače ne zna ispisati emoji i hrvatska slova
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days-ahead", type=int, default=DAYS_AHEAD, help="za koliko dana unaprijed")
    ap.add_argument("--any", action="store_true", help="bilo koji dan i sat (za testiranje)")
    ap.add_argument("--start-at", help="pričekaj do HH:MM pa kreni (npr. 08:00)")
    ap.add_argument("--retry-minutes", type=int, default=5,
                    help="ako termini još nisu otvoreni, pokušavaj ovoliko minuta")
    ap.add_argument("--show", action="store_true", help="prikaži prozor preglednika")
    ap.add_argument("--debug", action="store_true", help="spremi screenshot i podatke u mapu debug")
    ap.add_argument("--test-notify", action="store_true", help="pošalji probnu obavijest i izađi")
    args = ap.parse_args()

    topic = load_config().get("ntfy_topic")
    if args.test_notify:
        notify(topic, "🎾 Padel – probna obavijest", "Obavijesti rade!")
        return 0

    if args.start_at:
        wait_until(args.start_at)
    target = datetime.now(TZ).date() + timedelta(days=args.days_ahead)
    if not args.any and target.weekday() not in DAYS:
        print(f"{fmt_day(target)} nije pon/uto/sri – ništa za javiti.")
        return 0

    deadline = time.monotonic() + args.retry_minutes * 60
    try:
        while True:
            entries, courts, label = read_page(target, args.show, args.debug)
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
        rng = "" if args.any else f" od {EARLIEST}"
        notify(topic, "🎾 Padel – nema slobodnih termina",
               f"{fmt_day(target)}: nema slobodnog double terena ({DURATION} min{rng}).")
        return 0

    by_time: dict[str, list[str]] = {}
    for s in slots:
        by_time.setdefault(s.start, []).append(s.court.split(" ///")[0])
    lines = [f"📅 {fmt_day(target)} ({DURATION} min):"]
    lines += [f"  {t} – {', '.join(c)}" for t, c in by_time.items()]
    notify(topic, "🎾 Padel – slobodni termini!", "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
