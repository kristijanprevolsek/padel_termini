# padel_termini

Obavijest na mobitel o slobodnim **double** terenima (90 min, početak 17–21 h) u **Padel Embassyju**
za **ponedjeljak, utorak i srijedu**, i to u 8:00 kad se termini otvore (7 dana unaprijed).

Program na tvom računalu otvori javnu stranicu kluba
(<https://playtomic.com/clubs/padel-embassy>) u pregledniku Edge, prebaci tablicu na dan
za 7 dana, pročita slobodne termine i pošalje ti popis u aplikaciju **ntfy**. Rezerviraš sam,
u Playtomic aplikaciji. Program ništa ne rezervira.

> Playtomic blokira skripte koje izravno zovu njihov API, pa program čita samo ono što
> stranica prikaže u pregledniku. Ako Playtomic promijeni stranicu ili počne blokirati i to,
> program će javiti grešku.

## 1. Instalacija (jednom)

1. Instaliraj **Python** s <https://www.python.org/downloads/>. U instalaciji označi
   **„Add python.exe to PATH”**.
2. Preuzmi ovaj repozitorij (zeleni gumb **Code → Download ZIP**) i raspakiraj ga npr. u
   `Desktop\Cloude\playtomic_termini`.
3. Otvori **PowerShell** u tom folderu (u Exploreru: desni klik u folderu → *Open in Terminal*)
   i pokreni:

   ```powershell
   python -m pip install -r requirements.txt
   ```

   Edge već imaš, pa ne treba skidati poseban preglednik. Ako program javi da ne može
   pokrenuti preglednik, pokreni još: `python -m playwright install chromium`

## 2. Obavijesti na mobitelu

1. Instaliraj aplikaciju **ntfy** (Android/iOS) i u njoj **Subscribe to topic** s nekim
   teško pogodivim imenom, npr. `padel-embassy-k8x2q7`.
2. U folderu kopiraj `postavke.example.json` u `postavke.json` i u njega upiši to ime:

   ```json
   { "ntfy_topic": "padel-embassy-k8x2q7" }
   ```

3. Probaj:

   ```powershell
   python padel_obavijest.py --test-notify
   ```

## 3. Prvi test na pravoj stranici

```powershell
python padel_obavijest.py --any --days-ahead 1 --show --debug
```

Otvorit će se prozor preglednika, tablica će se pomaknuti na sutra, a na mobitel bi trebao
stići popis slobodnih double termina od 90 min (`--any` znači bilo koji sat).
Usporedi ga s tablicom na stranici.

**Ako ne radi**, u folderu `debug` su `stranica.png`, `stranica.html` i `odgovori.json`.
Pošalji ih (ili ispis iz PowerShella) pa ćemo prilagoditi program.

## 4. Automatsko praćenje

Program pamti što ti je već javio (`stanje.json`) i šalje obavijest **samo za nove slobodne
termine**: kad se otvori novi dan ili kad netko otkaže. Svaka provjera gleda sve
pon/uto/sri od danas do 7 dana unaprijed. Noću (23–7 h) ne provjerava, a greške javlja
najviše jednom u 2 sata.

U PowerShellu, **u folderu projekta**, napravi dva zadatka:

```powershell
# svakih 10 minuta
schtasks /create /tn "Padel provjera" /sc minute /mo 10 /tr "wscript.exe $PWD\tiho.vbs"
# pon/uto/sri u 7:58 – čeka točno 8:00, kad se otvori novi dan
schtasks /create /tn "Padel obavijest" /sc weekly /d MON,TUE,WED /st 07:58 /tr "wscript.exe $PWD\tiho.vbs pokreni.bat"
```

(Ako „Padel obavijest” već postoji, prvo ga obriši: `schtasks /delete /tn "Padel obavijest" /f`.)

`tiho.vbs` pokreće provjeru bez crnog prozora; preglednik se otvara izvan ekrana.
Dvije provjere se nikad ne pokreću istovremeno. Zapis svih provjera je u `zapis.txt`.

- **Računalo mora biti upaljeno i ti prijavljen** (zaključan ekran je u redu). U *Task Scheduler*
  → zadatak → *Properties* → *Conditions* možeš uključiti **„Wake the computer to run this task”**.
- Ručno pokretanje: `schtasks /run /tn "Padel provjera"`
- Brisanje: `schtasks /delete /tn "Padel provjera" /f`
- Da ti opet javi sve trenutne termine, obriši `stanje.json`.

## Postavke

Na vrhu `padel_obavijest.py`:

| Postavka | Zadano | Značenje |
|---|---|---|
| `DAYS` | `{0, 1, 2}` | pon, uto, sri |
| `EARLIEST` / `LATEST` | `17:00` / `21:00` | raspon početka termina |
| `DURATION` | `90` | trajanje u minutama |
| `DAYS_AHEAD` | `7` | koliko dana unaprijed se termini otvaraju |
