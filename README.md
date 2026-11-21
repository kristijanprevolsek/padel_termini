# padel_termini

Obavijest na mobitel o **novim** slobodnim **double** terenima (90 min) u **Padel Embassyju**:
radnim danom s početkom **17–21 h**, vikendom **9–12 h**, za sljedećih 7 dana. Provjera ide
svakih 10 minuta i u 8:00, kad se otvori novi dan.

Program na tvom računalu otvori javnu stranicu kluba
(<https://playtomic.com/clubs/padel-embassy>) u pregledniku Edge, strelicom prođe kroz
sljedećih 7 dana, pročita slobodne termine i pošalje ti popis u aplikaciju **ntfy**. Rezerviraš sam,
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
termine**: kad se otvori novi dan ili kad netko otkaže. Svaka provjera gleda sve dane od danas
do 7 dana unaprijed: **radne dane s početkom 17–21 h, vikende 9–12 h**. Noću (23–7 h) ne
provjerava, a greške javlja najviše jednom u 2 sata.

U PowerShellu, **u folderu projekta**, zalijepi cijeli blok. Napravi dva zadatka koja pokreću
`pythonw.exe` (Python bez prozora); ispis ide u `zapis.txt`:

```powershell
$py  = Join-Path (Split-Path (python -c "import sys; print(sys.executable)")) pythonw.exe
$dir = $PWD.Path
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew

# svakih 10 minuta
$a1 = New-ScheduledTaskAction -Execute $py -Argument "padel_obavijest.py --watch --log zapis.txt" -WorkingDirectory $dir
$t1 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "Padel provjera" -Action $a1 -Trigger $t1 -Settings $set -Force

# svaki dan u 7:58 – čeka točno 8:00, kad se otvori novi dan
$a2 = New-ScheduledTaskAction -Execute $py -Argument "padel_obavijest.py --watch --log zapis.txt --start-at 08:00" -WorkingDirectory $dir
$t2 = New-ScheduledTaskTrigger -Daily -At 07:58
Register-ScheduledTask -TaskName "Padel obavijest" -Action $a2 -Trigger $t2 -Settings $set -Force
```

`-Force` zamjenjuje postojeće zadatke istog imena. Zadaci rade i na bateriji i bude računalo
iz sleepa. Dvije provjere se nikad ne pokreću istovremeno, a preglednik se otvara izvan ekrana.

Test:

```powershell
Start-ScheduledTask "Padel provjera"
Start-Sleep 60; Get-Content zapis.txt -Tail 15 -Encoding utf8
Get-ScheduledTaskInfo "Padel provjera" | Select LastRunTime, LastTaskResult, NextRunTime
```

- **Računalo mora biti upaljeno i ti prijavljen** (zaključan ekran je u redu). U *Task Scheduler*
  → zadatak → *Properties* → *Conditions* možeš uključiti **„Wake the computer to run this task”**.
- Ručno pokretanje: `Start-ScheduledTask "Padel provjera"`
- Brisanje: `Unregister-ScheduledTask "Padel provjera" -Confirm:$false`
- Da ti opet javi sve trenutne termine, obriši `stanje.json`.

## Postavke

Na vrhu `padel_obavijest.py`:

| Postavka | Zadano | Značenje |
|---|---|---|
| `WORKDAY` | `17:00`–`21:00` | početak termina pon–pet |
| `WEEKEND` | `09:00`–`12:00` | početak termina sub–ned |
| `WINDOWS` | svi dani | koji dan koristi koji raspon (dan koji nije naveden se preskače) |
| `DURATION` | `90` | trajanje u minutama |
| `DAYS_AHEAD` | `7` | koliko dana unaprijed se termini otvaraju |
