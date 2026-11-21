# padel_termini

Obavijest na mobitel o slobodnim **double** terenima (90 min, od 19:00) u **Padel Embassyju**
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

## 4. Automatsko pokretanje pon/uto/sri u 8:00

U PowerShellu, **u folderu projekta**:

```powershell
schtasks /create /tn "Padel obavijest" /sc weekly /d MON,TUE,WED /st 07:58 /tr "$PWD\pokreni.bat"
```

(Ako putanja do foldera sadrži razmak, zadatak radije napravi ručno u aplikaciji *Task Scheduler*:
*Create Basic Task* → *Weekly* → pon, uto, sri u 07:58 → *Start a program* → `pokreni.bat`.)

`pokreni.bat` pričeka do 8:00, pročita termine za isti dan idući tjedan (ako termini kasne,
pokušava još 5 minuta) i pošalje obavijest. Zapis svakog pokretanja je u `zapis.txt`.

- **Računalo mora biti upaljeno** u 8:00. U *Task Scheduler* → *Padel obavijest* →
  *Properties* → *Conditions* možeš uključiti **„Wake the computer to run this task”**
  (radi iz sleepa, ne iz ugašenog računala).
- Ručno pokretanje: `schtasks /run /tn "Padel obavijest"`
- Brisanje: `schtasks /delete /tn "Padel obavijest" /f`

## Postavke

Na vrhu `padel_obavijest.py`:

| Postavka | Zadano | Značenje |
|---|---|---|
| `DAYS` | `{0, 1, 2}` | pon, uto, sri |
| `EARLIEST` / `LATEST` | `19:00` / `22:00` | raspon početka termina |
| `DURATION` | `90` | trajanje u minutama |
| `DAYS_AHEAD` | `7` | koliko dana unaprijed se termini otvaraju |
