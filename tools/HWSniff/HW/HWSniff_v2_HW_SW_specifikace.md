# HWSniff v2 — HW zapojení a finální stavová logika

## 1. Cíl v2

HWSniff v2 má být jednoduché, jednoznačné a „blbuvzdorné“ zařízení pro Raspberry Pi Zero 2 W.

Základní principy:

- bez displeje;
- 2 tlačítka: START a STOP;
- 2 DIP přepínače režimu;
- 4 stavové LED;
- ELATEC TWN4 jako čtečka;
- všechny hlavní ovládací GPIO soustředěné na fyzických pinech 29–40;
- každý stav má jednoznačnou LED signalizaci;
- žádné automatické pokračování do dalšího capture bez jasné uživatelské akce;
- chyby se musí zapisovat do logu s konkrétním důvodem.

## 2. GPIO mapa v2

| Funkce | Fyzický pin | BCM GPIO |
|---|---:|---:|
| START tlačítko | 29 | GPIO5 |
| GND | 30 | GND |
| STOP tlačítko | 31 | GPIO6 |
| DIP MODE 1 | 32 | GPIO12 |
| DIP MODE 2 | 33 | GPIO13 |
| GND | 34 | GND |
| LED1 zelená | 35 | GPIO19 |
| LED2 žlutá | 36 | GPIO16 |
| LED3 červená | 37 | GPIO26 |
| LED4 modrá | 38 | GPIO20 |
| GND | 39 | GND |
| Rezerva | 40 | GPIO21 |

### Tlačítka

Použít interní pull-up:

```text
GPIO5  / pin 29 ── START ── GND
GPIO6  / pin 31 ── STOP  ── GND
```

### DIP

Použít interní pull-up:

```text
GPIO12 / pin 32 ── DIP1 ── GND
GPIO13 / pin 33 ── DIP2 ── GND
```

```text
DIP OFF = HIGH
DIP ON  = LOW
```

### LED

Každá LED má vlastní sériový rezistor 330 Ω:

```text
GPIO19 / pin 35 ── 330 Ω ── GREEN LED  ── GND
GPIO16 / pin 36 ── 330 Ω ── YELLOW LED ── GND
GPIO26 / pin 37 ── 330 Ω ── RED LED    ── GND
GPIO20 / pin 38 ── 330 Ω ── BLUE LED   ── GND
```

LED jsou active-high.

## 3. DIP režimy

```text
DIP1 OFF = MAIN MODE
DIP1 ON  = SWEETP MODE
```

DIP2 je zatím rezervovaný. V aktuální v2:

```text
DIP2 OFF = povolený stav
DIP2 ON  = ERROR3
```

| DIP1 | DIP2 | Výsledek |
|---|---|---|
| OFF | OFF | MAIN MODE |
| ON | OFF | SWEETP MODE |
| OFF | ON | ERROR3 |
| ON | ON | ERROR3 |

Při bootu musí být oba DIP přepínače OFF. Jinak zařízení přejde do ERROR3.

## 4. LED význam

- **LED1 zelená** — READY, dobrá/ideální SweetP kvalita, úspěšný stav.
- **LED2 žlutá** — pracovní/mezní stav, použitelná SweetP kvalita, READ, SAVE.
- **LED3 červená** — chyba, nevyhovující SweetP kvalita, chybějící čtečka, neplatná DIP konfigurace.
- **LED4 modrá** — WLAN heartbeat.

Pokud je zařízení připojené k Wi‑Fi, modrá LED krátce blikne 1× každé 3 sekundy. Jinak je zhasnutá.

## 5. BOOT / SELF-TEST

Po zapnutí:

1. inicializace GPIO;
2. kontrola DIP;
3. LED self-test;
4. health check;
5. kontrola TWN4;
6. přechod do READY nebo chyby.

### LED self-test

Sekvence se provede 2×:

```text
GREEN ON  → OFF
YELLOW ON → OFF
RED ON    → OFF
BLUE ON   → OFF
```

Každý krok trvá přibližně 0,5 s.

## 6. READY

READY znamená, že HWSniff běží, health check prošel, TWN4 je připojená a DIP je platný.

```text
GREEN  = ON
YELLOW = OFF
RED    = OFF
BLUE   = WLAN heartbeat
```

## 7. ERROR1 — interní / fatální chyba

ERROR1 znamená, že HWSniff běží, ale detekoval fatální interní chybu, například chybu persistence, finalizace SAVE nebo jinou kritickou chybu.

```text
GREEN  = OFF
YELLOW = OFF
RED    = ON
```

Do logu se musí uložit konkrétní důvod.

## 8. ERROR2 — TWN4 není připojená

```text
GREEN + RED blikají synchronně 1× za sekundu
500 ms ON / 500 ms OFF
```

HWSniff každou sekundu kontroluje přítomnost TWN4. Jakmile je nalezena, provede health check a automaticky se vrátí do READY.

## 9. ERROR3 — neplatná DIP konfigurace

ERROR3 nastane vždy při DIP2 = ON.

Červená LED:

```text
ON 0,5 s
OFF 0,5 s
ON 0,5 s
OFF 0,5 s
ON 0,5 s
OFF 1,5 s
opakovat
```

3× červené bliknutí = ERROR3 / DIP konfigurace.

## 10. SWEETP MODE

Aktivace:

```text
READY → DIP1 ON → SWEETP
```

V SWEETP:

- MAIN capture nelze spustit;
- START se pro MAIN ignoruje;
- zařízení průběžně hledá tag;
- GREEN / YELLOW / RED zobrazují kvalitu pozice;
- BLUE dál nezávisle signalizuje WLAN.

DIP1 zpět OFF:

```text
SweetP stop → health check → READY
```

## 11. SweetP — finální pásma kvality

SweetP score není skutečné RF RSSI, ale odvozené skóre kvality/stability komunikace s tagem.

Praktická zkušenost: kolem 75 je čtení už velmi dobré, kolem 45 začíná skutečná hranice použitelnosti.

### Finální pásma v2

| SweetP score | Signalizace | Význam |
|---:|---|---|
| 75–100 | GREEN trvale | dobrá / ideální poloha |
| 56–74 | YELLOW trvale | použitelná poloha |
| 40–55 | YELLOW + RED střídavě blikají | hraniční / limitní poloha |
| 0–39 | RED trvale | špatná poloha / nevyhovující |

Pásmo 40–55 má přednost před základním barevným rozdělením a záměrně překrývá dřívější intuitivní hranici „žlutá vs. červená“. Je to explicitní varování, že tag je ještě čitelný, ale jsme už na limitu.

Doporučené střídání limitního pásma:

```text
YELLOW ON / RED OFF  250 ms
YELLOW OFF / RED ON  250 ms
opakovat
```

### Bez tagu

```text
GREEN  = OFF
YELLOW = OFF
RED    = OFF
```

### Hysteréze

Doporučená výchozí hysteréze je ±3 body, aby LED nekmitály kolem hranic.

## 12. MAIN MODE — positioning workflow

MAIN MODE:

```text
DIP1 OFF
DIP2 OFF
```

### První START

```text
READY → START → POSITIONING
```

POSITIONING používá stejnou SweetP signalizaci:

```text
75–100 → GREEN
56–74  → YELLOW
40–55  → YELLOW/RED střídavě
0–39   → RED
```

## 13. Druhý START — povolení READ

READ je povolen pouze při dostatečné kvalitě.

Doporučené pravidlo v2:

```text
score >= 56
```

tedy GREEN nebo YELLOW.

Při 40–55 nebo 0–39 se druhý START ignoruje a zařízení zůstává v POSITIONING.

## 14. READ

Po druhém START při vyhovující poloze:

```text
→ READ
```

Během READ se už SweetP kvalita nezobrazuje, aby uživatel neměl důvod readerem hýbat.

```text
GREEN = OFF
RED = OFF
YELLOW = rychle bliká
```

Doporučeně:

```text
200 ms ON / 200 ms OFF
```

Význam: **NEHÝBAT — probíhá čtení.**

## 15. Dokončení READ

Po úspěšném získání všech potřebných dat:

```text
GREEN + YELLOW + RED bliknou společně 5×
```

Doporučeně:

```text
500 ms ON
500 ms OFF
opakovat 5×
```

Význam: **čtení je hotové, reader lze oddálit od tagu.**

Poté aplikace přejde do SAVE.

## 16. SAVE

Během SAVE:

```text
GREEN = OFF
YELLOW = ON
RED = OFF
```

Význam: data se finalizují, ukládají a případně balí. Nový capture se nesmí spustit.

### SAVE OK

```text
YELLOW OFF
GREEN ON
→ READY
```

### SAVE FAIL

```text
→ ERROR1
RED ON
```

Do logu se zapíše přesný důvod.

## 17. STOP

### Krátký STOP

V aktivním MAIN workflow:

```text
request_stop
→ bezpečně ukončit aktuální práci
→ zavřít reader
→ zachovat validní již získaná data podle pravidel
→ READY
```

STOP nesmí být násilný kill procesu.

Po cancel může proběhnout krátká signalizace:

```text
RED krátce blikne
→ GREEN ON
→ READY
```

### Dlouhý STOP

Dlouhý stisk 3 s lze rezervovat pro bezpečné vypnutí Raspberry Pi. Pokud tato funkce nebude ve v2 požadována, může zůstat neaktivní.

## 18. WLAN heartbeat

BLUE je nezávislá na hlavním workflow.

### WLAN připojeno

```text
BLUE krátce blikne 1× každé 3 s
```

Doporučený pulse 100–150 ms.

### WLAN nepřipojeno

```text
BLUE OFF
```

## 19. Finální stavový automat

```text
POWER ON
   │
   ▼
BOOT / SELF TEST 2×
GREEN → YELLOW → RED → BLUE
   │
   ├── internal fail ─────────────→ ERROR1
   ├── TWN4 missing ──────────────→ ERROR2
   ├── invalid DIP ───────────────→ ERROR3
   ▼
READY
GREEN ON
   │
   ├── DIP1 ON ───────────────────→ SWEETP
   │                                  │
   │                           G/Y/YR/R quality
   │                                  │
   │                           DIP1 OFF
   │                                  │
   │                                  ▼
   │                                READY
   │
   └── START ──────────────────────→ POSITIONING
                                      │
                                SweetP quality
                                G / Y / YR / R
                                      │
                             START + score >= 56
                                      │
                                      ▼
                                    READ
                              YELLOW fast blink
                                      │
                                read complete
                                      │
                                      ▼
                       G+Y+R společně 5× bliknou
                                      │
                                      ▼
                                    SAVE
                               YELLOW solid
                                  │       │
                                 OK      FAIL
                                  │       │
                                  ▼       ▼
                                READY   ERROR1
```

Globálně v aktivním MAIN workflow:

```text
STOP → request_stop → bezpečný cancel → READY
```

## 20. Stručný přehled stavů

| Stav | LED |
|---|---|
| READY | GREEN ON |
| ERROR1 | RED ON |
| ERROR2 — TWN4 chybí | GREEN + RED blikají 1 Hz |
| ERROR3 — DIP | RED 3× po 0,5 s, poté 1,5 s pauza |
| SWEETP GOOD | GREEN ON |
| SWEETP USABLE | YELLOW ON |
| SWEETP BORDERLINE | YELLOW / RED střídavě |
| SWEETP BAD | RED ON |
| READ | YELLOW rychle bliká |
| READ COMPLETE | GREEN + YELLOW + RED 5× společně |
| SAVE | YELLOW ON |
| WLAN OK | BLUE krátký pulse každé 3 s |

## 21. Konfigurovatelné hodnoty

```text
SweetP GREEN threshold       = 75
SweetP YELLOW threshold      = 56
SweetP BORDERLINE low        = 40
SweetP BORDERLINE high       = 55
SweetP hysteresis            = 3

MAIN READ minimum score      = 56

ERROR2 blink                 = 500 ms
ERROR3 pulse                 = 500 ms
ERROR3 pause                 = 1500 ms
READ blink                   = 200 ms
READ complete blink count    = 5
READ complete interval       = 500 ms
WLAN heartbeat period        = 3 s
WLAN heartbeat pulse         = 100–150 ms
```

## 22. Návrhové zásady v2

1. Každá LED signalizace má jeden jasný význam.
2. BLUE WLAN je nezávislá na hlavním workflow.
3. DIP2 ON je v současné v2 vždy ERROR3.
4. MAIN capture nikdy nezačne při zjevně nevyhovující SweetP kvalitě.
5. Během READ se readerem nemá pohybovat.
6. Po dokončení READ dostane uživatel jasný signál, že reader lze oddálit.
7. SAVE musí skončit před návratem do READY.
8. TWN4 lze připojit dodatečně bez restartu.
9. Chybové stavy se mají samy zotavit, pokud je to bezpečné.
10. Každá interní chyba musí mít konkrétní záznam v logu.
11. STOP je request/cancel, nikoli násilné zabití procesu.
12. Stavový automat musí být deterministický a jednoduše testovatelný.

## 23. Verze dokumentu

```text
HWSniff HW/SW workflow
Version: v2
Target: Raspberry Pi Zero 2 W
```

Tento dokument je základ pro implementaci HWSniff v2 a následné fyzické testování.
