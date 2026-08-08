# VUSION / NTAG I²C Plus — Cold-Boot State Recurrence Analysis

Datum: 2026-08-08

Tento dokument navazuje na:

- `VUSION_NTAG_SRAM_MAILBOX_2026-08-07.md`
- `VUSION_NTAG_COLD_BOOT_TIMING_2026-08-08.md`

Cílem bylo zodpovědět původní otázku reléové kampaně: zda úplné odpojení hlavního napájení vrací dynamická pole `A/B` v 64B SRAM mailboxu do stejného výchozího stavu.

## Dataset

Zdroj: `vusion_experiment_v2_20260808_021438.zip`

```text
UID:              04367F5A2D7280
čtečka:           TWN4/B1.64/NCF5.20/PRS1.04
úspěšné capture:  205 / 205
NFC operace:      strict read-only
```

Úspěšné skupiny:

```text
baseline_start   30× OFF 15 s
OFF 1 s          20×
OFF 2 s          20×
OFF 5 s          25×
OFF 10 s         25×
OFF 15 s         30×
OFF 30 s         20×
OFF 60 s         15×
baseline_mid     20× OFF 15 s
```

Celkem je tedy k dispozici 205 prvních post-boot SRAM frame, z toho 115 po OFF >= 15 s, 35 po OFF >= 30 s a 15 po OFF = 60 s.

## Přímý test resetu A/B

Mezi 205 prvními post-boot rámci nebyla nalezena žádná přesná duplicita:

```text
stejné A[16]:          0
stejné B[16]:          0
stejné A+B[32]:        0
stejné dynamic[34]:    0
```

Ani 16bit trailer se neopakoval:

```text
unikátní trailer: 205 / 205
```

### Závěr

Pokud relé skutečně odpojuje hlavní napájení MCU a dlouhé OFF intervaly představují skutečný cold boot, data nepodporují jednoduchý model:

```text
power-on -> pevný seed/state -> stejný první A/B
```

Jednoduchý resetovatelný generátor s konstantním počátečním stavem je tímto experimentem silně oslaben.

Nejde ale o absolutní důkaz, dokud nebude fyzicky ověřeno, že VDD CC2510 během OFF opravdu spadne na stav odpovídající úplnému power-off / POR.

## Přesná 16B cross-role recurrence

Navzdory absenci fixního post-reset rámce se v 205cyklovém datasetu objevila nová úplná 16B shoda:

```text
49 B6 37 D4 1C 0A 86 23 5B 79 A2 78 21 D8 59 BA
```

Výskyt:

```text
cycle 9:  B
cycle 18: A
```

tedy:

```text
C009B == C018A
```

To znovu potvrzuje předchozí nález, že pole A a B mohou nést hodnoty ze stejného nebo příbuzného 128bitového stavového prostoru.

## Další dlouhé exact recurrence

V dynamické 32B oblasti byly nalezeny mimo jiné:

```text
16 B  cycle   9 <-> 18
15 B  cycle  25 <-> 203
14 B  cycle 118 <-> 137
14 B  cycle  27 <-> 167
13 B  cycle 120 <-> 194
12 B  cycle  46 <-> 153
```

Recurrence přechází i mezi různými OFF skupinami. To oslabuje jednoduchý model, ve kterém délka OFF sama vybírá oddělený datový režim.

## N-gram recurrence v 205 cyklech

Opakované exact skupiny mezi různými cykly:

```text
4 B  : 393
6 B  : 129
8 B  : 82
10 B : 45
12 B : 18
13 B : 12
14 B : 7
15 B : 3
16 B : 1
```

Tím se dále potvrzuje, že A/B nejsou nezávislé fresh-random hodnoty.

## Near-restart analýza — Hammingova vzdálenost

### A, 128 bitů

```text
mean: 63.91 / 128
min:  33 / 128
max:  84 / 128
```

Nejnižší A vzdálenost:

```text
cycle 16 <-> cycle 131 = 33 bitů
```

### B, 128 bitů

```text
mean: 63.85 / 128
min:  31 / 128
max:  82 / 128
```

Nejnižší B vzdálenost:

```text
cycle 37 <-> cycle 129 = 31 bitů
```

### A+B, 256 bitů

```text
mean:   127.76 / 256
median: 128 / 256
min:     82 / 256
max:    156 / 256
```

Nejnižší A+B vzdálenost:

```text
cycle 96 <-> cycle 113 = 82 bitů
```

### Dynamic A+B+trailer, 272 bitů

```text
mean:   135.75 / 272
median: 136 / 272
min:     92 / 272
max:    168 / 272
```

Průměry jsou blízko hodnotám očekávaným u silně proměnlivých dat, ale extrémně nízká minima spolu s exact n-gram recurrence podporují existenci skutečné vnitřní struktury / příbuzných stavů.

To není důkaz konkrétního PRNG, šifry ani challenge-response algoritmu.

## Vliv OFF délky na A+B

Porovnání Hammingovy vzdálenosti A+B:

```text
stejný OFF čas:    mean 127.56 / 256
rozdílný OFF čas:  mean 127.81 / 256
```

Rozdíl je přibližně 0.26 bitu z 256 a je prakticky zanedbatelný.

### Závěr

V samotném obsahu A+B se neprojevila jednoduchá hranice typu:

```text
1–10 s OFF = starý stav
15–60 s OFF = reset na pevný nový stav
```

Takový restart v payloadu není vidět.

## READY timing zůstává samostatný fyzický signál

Průměrný čas do `SRAM_RF_READY`:

```text
OFF 1 s:   ~0.481 s
OFF 2 s:   ~0.481 s
OFF 5 s:   ~0.482 s
OFF 10 s:  ~0.482 s
OFF 15 s:  ~0.537 s
OFF 30 s:  ~0.557 s
OFF 60 s:  ~0.555 s
```

Timing tedy jasně mění režim mezi krátkým a delším OFF, i když A/B se nevrací na jeden pevný začátek.

To znamená, že délka OFF mění fyzický boot/retention stav zařízení, ale tento stav se nepřekládá do jednoduchého fixního resetu dynamického 32B payloadu.

## Sousední cykly a jednoduchá perioda

Sousední cykly nejsou významně podobnější než všechny dvojice:

```text
sousední mean Hamming(A+B): ~127.81 / 256
všechny dvojice:            ~127.76 / 256
```

Nebyla nalezena ani přesvědčivá jednoduchá perioda podle cycle lag.

Aktuální závěr tedy zůstává:

```text
recurrence ano
jednoduchý krátký periodický restart neprokázán
```

## Aktualizovaný pracovní model

Současná data nejlépe odpovídají některé z těchto tříd:

1. persistentní stav přežívající power cycle v nevolatilním zdroji;
2. nový vstup při každém bootu (timing, oscilátor, RF lifecycle, counter, entropy apod.);
3. větší deterministický stavový prostor / tabulka / interní sekvence s opakovanými bloky;
4. kombinace persistentního stavu a proměnného boot vstupu.

Z pouze SRAM dat zatím nelze bezpečně určit konkrétní mechanismus.

## Rozhodnutí pro další postup

### Dalších 10 stejných cold bootů

Nedoporučeno. Dataset 205 post-boot frame je už dostatečný pro závěr, že jednoduchý fixní post-reset A/B stav nevidíme.

### Retention boundary

Má smysl pouze jako samostatná hardwarová otázka. V2.1 boundary follow-up může dokončit mapování přechodu timing režimu mezi 10–15 s a boot-before-RF hranice, ale už není hlavní cestou k původu A/B.

### Přesun na CC2510 stock firmware

Toto je nyní hlavní doporučená výzkumná větev.

NFC/SRAM cesta už poskytla:

- stock NTAG pass-through handshake;
- přesný 64B frame layout;
- SES ID v hlavičce;
- stovky fyzických payloadů;
- potvrzené 12–16B recurrence;
- cross-role A/B recurrence;
- vyloučení jednoduchého fixního cold-boot restartu;
- vyloučení několika jednoduchých A->B transformací a běžných checksum/CRC hypotéz traileru.

Další zásadní otázky jsou nyní přímo ve stock kódu CC2510:

```text
kdo skládá C0 01 01 01 ...
kde se tvoří A a B
odkud se bere stav / seed / counter
jak vzniká trailer
kde se zapisuje 64B NTAG SRAM
```

## Bezpečný CC2510 postup

Až bude HW debugger:

1. identifikovat GND/VDD/RESET_N/DD/DC;
2. pouze CHIP ID / debug status / detect;
3. pokud je debug locked, STOP — žádný unlock ani mass erase;
4. pokud je flash čitelná, udělat dva nezávislé dumpy;
5. porovnat SHA-256 a binární shodu;
6. analyzovat pouze kopie dumpu.

První offline kotvy pro hledání ve firmware:

```text
C0 01 01 01
C9 D0 2C AA
NTAG 64B SRAM transfer
I2C obsluha
NC_REG / NS_REG lifecycle
display / EPD state
```

## Jediné doporučené fyzické ověření před debuggerem

Pokud je to snadné, jednou změřit VDD CC2510 během relé OFF a potvrdit, že při 30/60 s opravdu padá na plný power-off / POR stav.

Tím se odstraní poslední velká alternativa, že MCU nebo část jeho stavu zůstává nějakou cestou napájena.

## Finální závěr

Cold-boot série přímo odpověděla na původní hypotézu:

```text
cold boot -> stejný seed -> stejný první A/B
```

V pozorované podobě se **nepotvrdila**.

Po 205 fyzických capture není žádný stejný A, B, A+B ani celý 34B dynamický frame, a to ani při opakovaných 30s a 60s OFF.

Současně ale dál existují přesné dlouhé recurrence a cross-role A/B shody.

Nejpřesnější současný popis je proto:

> VUSION používá strukturovaný stavový mechanismus s opakovanými interními hodnotami, ale jeho první post-boot výstup není jednoduše resetován na jeden konstantní A/B stav.

Po dokončení V2.1 boundary follow-up už není důvod pouštět další velké NFC/cold-boot série. Hlavní další krok je read-only výzkum stock CC2510 firmwaru.