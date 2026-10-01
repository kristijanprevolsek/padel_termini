# padel_termini

Skripta za obavijesti o slobodnim terminima i (opcionalno) automatsku rezervaciju padel termina na **Playtomicu** u klubu **Padel Embassy (Zagreb)**.

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

## Dnevna obavijest o otvorenim terminima (preporučeno)

Termini u Padel Embassyju otvaraju se **7 dana unaprijed u 08:00**. Workflow
`.github/workflows/book.yml` svaki **ponedjeljak, utorak i srijedu** u 08:00 provjeri termine koji su
se upravo otvorili (isti dan idući tjedan) i pošalje ti obavijest sa slobodnim double terminima
(90 min, od 19:00) i linkom na klub, pa **rezerviraš sam**. Ne treba mu tvoja Playtomic lozinka.

Primjer obavijesti:

```
🎾 Padel – otvoreni termini (90 min, od 19:00)
📅 pon 12.10.:
  19:00 – Teren 1, Teren 2
  20:30 – Teren 1
```

### ⚠️ Mora raditi s kućne mreže

Playtomic (od 2026.) blokira zahtjeve s IP adresa datacentara, uključujući GitHubove servere
(odgovor `403 Request blocked`). Zato skripta mora raditi na računalu na kućnoj mreži
(PC, Mac, Raspberry Pi...). Dvije mogućnosti:

**A) Self-hosted GitHub runner** (workflow ostaje isti):
1. U repou: **Settings → Actions → Runners → New self-hosted runner** i slijedi upute za svoj OS
   (instaliraj ga kao servis da radi i nakon restarta). Računalo mora biti upaljeno u 8:00.
2. Dodaj repo varijablu `RUNNER` = `self-hosted`. Bez nje se workflow ne pokreće po rasporedu.

**B) Obični cron / Task Scheduler** na svom računalu, pon/uto/sri u 07:55:

```bash
55 7 * * 1-3  cd ~/padel_termini && NTFY_TOPIC=... .venv/bin/python playtomic_booker.py --notify-only --exact-offset 7 --start-at 08:00 --poll 10 --poll-timeout 300
```

### Postavljanje obavijesti (ntfy, najjednostavnije)

1. Instaliraj aplikaciju **ntfy** (Android / iOS) i pretplati se na topic s nekim teško pogodivim
   imenom, npr. `padel-embassy-k8x2q` (svatko tko zna ime topica može čitati poruke).
2. U GitHub repou: **Settings → Secrets and variables → Actions → New repository secret**:
   `NTFY_TOPIC` = `padel-embassy-k8x2q`.
3. **Actions → Padel termini → Run workflow**: pošalje obavijest s trenutnim stanjem termina,
   pa odmah vidiš radi li sve.

Umjesto ntfy (ili uz njega) možeš koristiti Telegram: napravi bota preko `@BotFather` i dodaj secrete
`TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID`.

Ako skripta padne (npr. Playtomic promijeni API), dobiješ obavijest „❌ Padel – greška“, a
GitHub ti dodatno pošalje e-mail o neuspjelom workflowu.

Lokalno:

```bash
NTFY_TOPIC=padel-embassy-k8x2q python playtomic_booker.py --test-notify
NTFY_TOPIC=padel-embassy-k8x2q python playtomic_booker.py --notify-only --exact-offset 7
```

### Automatska rezervacija (opcionalno)

Ako ipak želiš da workflow sam rezervira, dodaj secrete `PLAYTOMIC_EMAIL` i `PLAYTOMIC_PASSWORD`
i repo varijablu `BOOKING_MODE` = `book`. Obavijest tada javlja što je rezervirano, a što nije.
