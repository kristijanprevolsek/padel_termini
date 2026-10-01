#!/usr/bin/env python3
"""Automatska rezervacija padel termina na Playtomicu (Padel Embassy, Zagreb).

Traži slobodne DOUBLE terene u trajanju od 90 minuta s početkom od 19:00
(pon/uto/sri) i rezervira prvi odgovarajući termin.

Koristi neslužbeni Playtomic API (isti kao web/mobilna aplikacija), pa se
ponašanje može promijeniti bez najave. Uvijek prvo pokreni s --dry-run.

Vjerodajnice se čitaju iz varijabli okruženja:
    PLAYTOMIC_EMAIL, PLAYTOMIC_PASSWORD
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

API = "https://api.playtomic.io"
TZ = ZoneInfo("Europe/Zagreb")
ZAGREB_COORDS = "45.8150,15.9819"
WEEKDAY_NAMES = {"pon": 0, "uto": 1, "sri": 2, "cet": 3, "pet": 4, "sub": 5, "ned": 6}
STATE_FILE = Path(__file__).with_name("booked.json")

log = logging.getLogger("playtomic")


@dataclass
class Slot:
    resource_id: str
    resource_name: str
    start_local: datetime
    duration: int
    price: str


class PlaytomicClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (padel_termini booker)",
                "Accept": "application/json",
                "X-Requested-With": "com.playtomic.web",
            }
        )
        self.user_id: str | None = None

    # --- auth ---------------------------------------------------------------
    def login(self, email: str, password: str) -> None:
        r = self.session.post(
            f"{API}/v3/auth/login", json={"email": email, "password": password}, timeout=20
        )
        _raise_for_status(r, "Prijava nije uspjela")
        data = r.json()
        self.session.headers["Authorization"] = f"Bearer {data['access_token']}"
        self.user_id = data["user_id"]
        log.info("Prijavljen kao %s (user_id=%s)", email, self.user_id)

    # --- tenant / courts ----------------------------------------------------
    def find_tenant(self, name: str) -> dict:
        r = self.session.get(
            f"{API}/v1/tenants",
            params={
                "tenant_name": name,
                "coordinate": ZAGREB_COORDS,
                "radius": 50000,
                "sport_id": "PADEL",
                "playtomic_status": "ACTIVE",
                "size": 20,
            },
            timeout=20,
        )
        _raise_for_status(r, "Pretraga klubova nije uspjela")
        tenants = r.json()
        matches = [t for t in tenants if name.lower() in t.get("tenant_name", "").lower()]
        if not matches:
            found = ", ".join(t.get("tenant_name", "?") for t in tenants) or "ništa"
            raise SystemExit(f"Klub '{name}' nije pronađen. Pronađeno: {found}")
        if len(matches) > 1:
            log.warning(
                "Više klubova odgovara '%s': %s — koristim prvi. Za preciznost postavi --tenant-id.",
                name,
                ", ".join(f"{t['tenant_name']} ({t['tenant_id']})" for t in matches),
            )
        return matches[0]

    def get_tenant(self, tenant_id: str) -> dict:
        r = self.session.get(f"{API}/v1/tenants/{tenant_id}", timeout=20)
        _raise_for_status(r, "Dohvat kluba nije uspio")
        return r.json()

    def availability(self, tenant_id: str, day: date) -> list[dict]:
        r = self.session.get(
            f"{API}/v1/availability",
            params={
                "sport_id": "PADEL",
                "tenant_id": tenant_id,
                "local_start_min": f"{day.isoformat()}T00:00:00",
                "local_start_max": f"{day.isoformat()}T23:59:59",
            },
            timeout=20,
        )
        _raise_for_status(r, "Dohvat slobodnih termina nije uspio")
        return r.json()

    # --- booking ------------------------------------------------------------
    def book(self, tenant_id: str, slot: Slot, payment_prefs: list[str], players: int) -> dict:
        start_utc = slot.start_local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S")
        intent_body = {
            "allowed_payment_method_types": [
                "OFFER", "CASH", "MERCHANT_WALLET", "DIRECT", "SWISH", "IDEAL",
                "BANCONTACT", "PAYTRAIL", "CREDIT_CARD", "QUICK_PAY",
            ],
            "user_id": self.user_id,
            "cart": {
                "requested_item": {
                    "cart_item_type": "CUSTOMER_MATCH",
                    "cart_item_voucher_id": None,
                    "cart_item_data": {
                        "supports_split_payment": True,
                        "number_of_players": players,
                        "tenant_id": tenant_id,
                        "resource_id": slot.resource_id,
                        "start": start_utc,
                        "duration": slot.duration,
                        "match_registrations": [{"user_id": self.user_id, "pay_now": True}],
                    },
                }
            },
        }
        r = self.session.post(f"{API}/v1/payment_intents", json=intent_body, timeout=20)
        _raise_for_status(r, "Kreiranje rezervacije nije uspjelo")
        intent = r.json()
        intent_id = intent["payment_intent_id"]

        methods = intent.get("available_payment_methods", [])
        method = _pick_payment_method(methods, payment_prefs)
        if method is None:
            available = ", ".join(m.get("method_type", "?") for m in methods) or "nijedna"
            raise RuntimeError(
                f"Nijedna od željenih metoda plaćanja {payment_prefs} nije dostupna. "
                f"Dostupne: {available}"
            )
        log.info("Metoda plaćanja: %s", method.get("method_type"))

        r = self.session.patch(
            f"{API}/v1/payment_intents/{intent_id}",
            json={
                "selected_payment_method_id": method["payment_method_id"],
                "selected_payment_method_data": None,
            },
            timeout=20,
        )
        _raise_for_status(r, "Odabir metode plaćanja nije uspio")

        r = self.session.post(f"{API}/v1/payment_intents/{intent_id}/confirmation", timeout=20)
        _raise_for_status(r, "Potvrda rezervacije nije uspjela")
        result = r.json()
        status = result.get("status")
        if status not in (None, "SUCCEEDED", "PROCESSING"):
            raise RuntimeError(f"Neočekivan status rezervacije: {status} — {json.dumps(result)[:500]}")
        return result


def _pick_payment_method(methods: list[dict], prefs: list[str]) -> dict | None:
    for pref in prefs:
        for m in methods:
            if m.get("method_type", "").upper() == pref.upper():
                return m
    return None


def _raise_for_status(r: requests.Response, msg: str) -> None:
    if not r.ok:
        raise RuntimeError(f"{msg}: HTTP {r.status_code} — {r.text[:500]}")


# --- slot selection -----------------------------------------------------------
def double_courts(tenant: dict) -> dict[str, str]:
    """Vrati {resource_id: naziv} za sve DOUBLE padel terene kluba."""
    courts = {}
    for res in tenant.get("resources", []):
        props = res.get("properties", {}) or {}
        if res.get("sport_id", "PADEL") != "PADEL":
            continue
        size = str(props.get("resource_size", "")).lower()
        name = res.get("name", res["resource_id"])
        if size == "double" or (not size and "double" in name.lower()):
            courts[res["resource_id"]] = name
    return courts


def parse_slots(raw: list[dict], courts: dict[str, str], times_utc: bool) -> list[Slot]:
    slots = []
    for entry in raw:
        rid = entry.get("resource_id")
        if rid not in courts:
            continue
        for s in entry.get("slots", []):
            naive = datetime.fromisoformat(f"{entry['start_date']}T{s['start_time']}")
            if times_utc:
                start = naive.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
            else:
                start = naive.replace(tzinfo=TZ)
            slots.append(Slot(rid, courts[rid], start, int(s["duration"]), str(s.get("price", ""))))
    return slots


def select_slots(slots: list[Slot], day: date, duration: int, earliest: str, latest: str,
                 preferred: list[str]) -> list[Slot]:
    e_h, e_m = map(int, earliest.split(":"))
    l_h, l_m = map(int, latest.split(":"))
    lo = datetime(day.year, day.month, day.day, e_h, e_m, tzinfo=TZ)
    hi = datetime(day.year, day.month, day.day, l_h, l_m, tzinfo=TZ)
    ok = [s for s in slots if s.duration == duration and lo <= s.start_local <= hi
          and s.start_local.date() == day]

    def rank(s: Slot) -> tuple:
        pref_idx = next((i for i, p in enumerate(preferred) if p.lower() in s.resource_name.lower()),
                        len(preferred))
        return (s.start_local, pref_idx, s.resource_name)

    return sorted(ok, key=rank)


# --- state --------------------------------------------------------------------
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# --- main ---------------------------------------------------------------------
def target_dates(args: argparse.Namespace) -> list[date]:
    today = datetime.now(TZ).date()
    weekdays = {WEEKDAY_NAMES[d.strip().lower()] for d in args.days.split(",")}
    if args.exact_offset is not None:
        candidates = [today + timedelta(days=args.exact_offset)]
    else:
        candidates = [today + timedelta(days=i) for i in range(args.days_ahead + 1)]
    return [d for d in candidates if d.weekday() in weekdays]


def run_once(client: PlaytomicClient, tenant_id: str, courts: dict[str, str],
             dates: list[date], args: argparse.Namespace, state: dict) -> list[date]:
    """Pokušaj rezervirati sve datume; vrati datume koji su i dalje neriješeni."""
    pending = []
    for day in dates:
        key = day.isoformat()
        if key in state:
            log.info("%s: već rezervirano (%s) — preskačem", key, state[key].get("court"))
            continue
        raw = client.availability(tenant_id, day)
        candidates = select_slots(
            parse_slots(raw, courts, args.times_utc), day, args.duration,
            args.earliest, args.latest, args.prefer_court,
        )
        if not candidates:
            log.info("%s: nema slobodnih double terena (%d min, %s–%s)",
                     key, args.duration, args.earliest, args.latest)
            pending.append(day)
            continue

        for s in candidates:
            log.info("%s: slobodno %s %s (%s)", key, s.start_local.strftime("%H:%M"),
                     s.resource_name, s.price)
        if args.dry_run:
            log.info("%s: [dry-run] rezervirao bih %s u %s", key, candidates[0].resource_name,
                     candidates[0].start_local.strftime("%H:%M"))
            continue

        booked = False
        for s in candidates:
            try:
                result = client.book(tenant_id, s, args.payment, args.players)
            except RuntimeError as exc:
                log.warning("%s: rezervacija %s %s nije uspjela: %s", key,
                            s.start_local.strftime("%H:%M"), s.resource_name, exc)
                continue
            log.info("%s: REZERVIRANO %s u %s (%s)", key, s.resource_name,
                     s.start_local.strftime("%H:%M"), s.price)
            state[key] = {
                "court": s.resource_name,
                "start": s.start_local.isoformat(),
                "duration": s.duration,
                "price": s.price,
                "payment_intent": result.get("payment_intent_id"),
            }
            save_state(state)
            booked = True
            break
        if not booked:
            pending.append(day)
    return pending


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--club", default="Padel Embassy", help="naziv kluba za pretragu")
    p.add_argument("--tenant-id", help="Playtomic tenant_id kluba (preskače pretragu)")
    p.add_argument("--days", default="pon,uto,sri", help="dani u tjednu (pon,uto,sri,cet,pet,sub,ned)")
    p.add_argument("--earliest", default="19:00", help="najraniji početak termina (HH:MM)")
    p.add_argument("--latest", default="22:00", help="najkasniji početak termina (HH:MM)")
    p.add_argument("--duration", type=int, default=90, help="trajanje u minutama")
    p.add_argument("--players", type=int, default=4)
    p.add_argument("--days-ahead", type=int, default=14, help="koliko dana unaprijed tražiti")
    p.add_argument("--exact-offset", type=int,
                   help="traži samo datum danas+N (npr. dan kad se termini otvaraju)")
    p.add_argument("--prefer-court", action="append", default=[],
                   help="dio naziva terena koji ima prednost (može više puta)")
    p.add_argument("--payment", default="CASH,MERCHANT_WALLET,OFFER,DIRECT,CREDIT_CARD",
                   help="redoslijed željenih metoda plaćanja")
    p.add_argument("--times-utc", action="store_true",
                   help="tretiraj vremena iz /availability kao UTC (provjeri s --dry-run)")
    p.add_argument("--poll", type=int, default=0,
                   help="ponavljaj svakih N sekundi dok se ne rezervira (0 = jednom)")
    p.add_argument("--poll-timeout", type=int, default=900, help="maks. trajanje pollinga u sekundama")
    p.add_argument("--dry-run", action="store_true", help="samo ispiši što bi se rezerviralo")
    p.add_argument("--list-courts", action="store_true", help="ispiši terene kluba i izađi")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    args.payment = [m.strip() for m in args.payment.split(",") if m.strip()]

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    client = PlaytomicClient()
    tenant = client.get_tenant(args.tenant_id) if args.tenant_id else client.find_tenant(args.club)
    tenant_id = tenant["tenant_id"]
    log.info("Klub: %s (tenant_id=%s)", tenant.get("tenant_name"), tenant_id)

    if args.list_courts:
        for res in tenant.get("resources", []):
            print(f"{res['resource_id']}  {res.get('name'):<25} {json.dumps(res.get('properties', {}))}")
        return 0

    courts = double_courts(tenant)
    if not courts:
        raise SystemExit("Nisu pronađeni double tereni. Pokreni --list-courts i provjeri properties.")
    log.info("Double tereni: %s", ", ".join(courts.values()))

    if not args.dry_run:
        email, password = os.environ.get("PLAYTOMIC_EMAIL"), os.environ.get("PLAYTOMIC_PASSWORD")
        if not email or not password:
            raise SystemExit("Postavi PLAYTOMIC_EMAIL i PLAYTOMIC_PASSWORD.")
        client.login(email, password)

    dates = target_dates(args)
    if not dates:
        log.info("Nema ciljanih datuma u zadanom rasponu.")
        return 0
    log.info("Ciljani datumi: %s", ", ".join(d.strftime("%a %d.%m.") for d in dates))

    state = load_state()
    deadline = time.monotonic() + args.poll_timeout
    while True:
        pending = run_once(client, tenant_id, courts, dates, args, state)
        if not pending or args.poll <= 0 or args.dry_run or time.monotonic() >= deadline:
            break
        log.info("Još neriješeno: %s — ponovno za %ds", ", ".join(map(str, pending)), args.poll)
        time.sleep(args.poll)
        dates = pending

    if pending and not args.dry_run:
        log.warning("Nije rezervirano za: %s", ", ".join(map(str, pending)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
