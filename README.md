# padel_termini

Skripta za automatsku rezervaciju padel termina na **Playtomicu** u klubu **Padel Embassy (Zagreb)**.

Zadano traži:
- samo **double** terene
- termine od **90 minuta**
- s početkom **od 19:00 do 22:00**
- **ponedjeljak, utorak, srijeda**

i rezervira najraniji slobodni termin za svaki takav dan.

> ⚠️ Koristi neslužbeni Playtomic API (isti koji koristi njihova aplikacija). Može se promijeniti
> bez najave, a automatizacija možda nije u skladu s uvjetima korištenja Playtomica — koristi na vlastitu odgovornost.

## Instalacija

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PLAYTOMIC_EMAIL="tvoj@email.com"
export PLAYTOMIC_PASSWORD="lozinka"
```

## Prvo provjeri (bez rezervacije)

```bash
# 1. Pronađi klub i ispiši sve terene (provjeri da su double tereni ispravno označeni)
python playtomic_booker.py --list-courts

# 2. Što bi skripta rezervirala u sljedećih 14 dana
python playtomic_booker.py --dry-run
```

Usporedi ispisana vremena s onima u Playtomic aplikaciji. Ako su pomaknuta za 1–2 sata,
dodaj `--times-utc`. Ako pretraga pronađe krivi klub, zapiši `tenant_id` iz ispisa i koristi `--tenant-id`.

## Rezervacija

```bash
# Rezerviraj sve slobodne pon/uto/sri termine u sljedećih 14 dana
python playtomic_booker.py

# Čekaj otvaranje termina: traži samo datum za 7 dana, ponavljaj svakih 20 s do 15 min
python playtomic_booker.py --exact-offset 7 --poll 20 --poll-timeout 900
```

Uspješne rezervacije zapisuju se u `booked.json`, pa ponovno pokretanje ne rezervira isti dan dvaput.

Korisne opcije:

| Opcija | Zadano | Opis |
|---|---|---|
| `--days` | `pon,uto,sri` | dani u tjednu |
| `--earliest` / `--latest` | `19:00` / `22:00` | raspon početka termina |
| `--duration` | `90` | trajanje u minutama |
| `--prefer-court` | – | dio naziva terena koji ima prednost (može više puta) |
| `--payment` | `CASH,MERCHANT_WALLET,OFFER,DIRECT,CREDIT_CARD` | redoslijed metoda plaćanja |
| `--tenant-id` | – | izravno zadaj klub |

**Plaćanje:** ako klub traži plaćanje karticom s 3D Secure potvrdom, skripta to ne može dovršiti.
Najbolje radi s plaćanjem u klubu (`CASH`) ili s Playtomic novčanikom kluba (`MERCHANT_WALLET`).

## Automatski preko GitHub Actions

Workflow `.github/workflows/book.yml` svaki dan pokušava rezervirati datum koji je točno
`BOOKING_DAYS_AHEAD` dana unaprijed (jedan datum po danu → nema duplih rezervacija).

1. **Settings → Secrets → Actions**: dodaj `PLAYTOMIC_EMAIL` i `PLAYTOMIC_PASSWORD`.
2. **Settings → Variables → Actions**:
   - `BOOKING_DAYS_AHEAD` – koliko dana unaprijed klub otvara termine (npr. `7`)
   - `PLAYTOMIC_TENANT_ID` – (opcionalno) ID kluba
   - `BOOKING_ENABLED` = `true` – uključuje dnevno zakazano pokretanje
3. Prilagodi `cron` u workflowu vremenu kad klub otvara nove termine (cron je u UTC-u).
4. Ručno pokreni workflow (*Run workflow*, dry run uključen) za provjeru.
