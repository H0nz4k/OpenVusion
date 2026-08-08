# VUSION V2.1 — boundary follow-up (částečný výsledek)

**Zdroj:** `vusion_v21_boundaries_20260808_043923.zip`  
**Datum vyhodnocení:** 2026-08-08  
**UID:** `04367F5A2D7280`  
**Režim:** strict read-only

---

## 1. Důležitá informace: V2.1 nedoběhla do konce

Archiv neobsahuje kompletní plánovanou boundary kampaň.

Plán obsahoval sweep:

```text
OFF: 0.5, 1, 2, 5, 8, 10, 11, 12, 13, 14, 15, 18 s
+
boot-before-RF: 0, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1, 1.5, 2 s
+
závěrečný baseline
```

Ve skutečnosti byly dokončeny pouze:

```text
P00_off_0p5   8/8 SUCCESS
P01_off_1     8/8 SUCCESS
P02_off_2     8/8 SUCCESS
P05_off_5     1/2 SUCCESS
```

Druhý cyklus série `P05_off_5` skončil:

```text
SRAM_RF_READY nebyl během okna zachycen
```

a tím se celá kampaň zastavila.

Celkem tedy:

```text
25 úspěšných SRAM capture
1 timeout
```

Další plánované série se vůbec nespustily.

---

# 2. Co timeout ve 5s OFF cyklu skutečně ukázal

V chybovém cyklu:

```text
OFF = 5 s
boot wait = 10 s
ready window = 3 s
```

byl tag normálně nalezen a RF field byl přítomen.

Celou sledovanou dobu ale session stav zůstal:

```text
NC_REG = 0x19
NS_REG = 0x01
```

tedy:

```text
PTHRU = 0
SRAM_RF_READY = 0
RF_FIELD_PRESENT = 1
```

Bylo provedeno přibližně 229 session readů až přes 3.46 s od začátku sledování, ale stock MCU tentokrát vůbec nepřešlo do běžné sekvence:

```text
0x19/0x01
  ->
0x7C/0x41 nebo 0x7C/0x29
  ->
SRAM_RF_READY
```

To je důležité:

> Nešlo jen o to, že READY přišlo o několik desítek milisekund později. V tomto jednom cyklu se mailbox handshake v několikanásobně delším okně vůbec nerozběhl.

Z jednoho výskytu ale nelze určit příčinu.

Možnosti zahrnují například:

- jednorázový firmware/state-machine stav;
- RF trigger, který stock firmware tentokrát neobsloužil;
- transient po power-cycle;
- jiný interní stav MCU;
- případně experimentální/readout artefakt.

Proto tento jediný timeout **není důkaz nové retention hranice na 5 s**.

---

# 3. READY timing úspěšných V2.1 cyklů

## OFF 0.5 s

```text
N = 8
min    = 0.476055 s
max    = 0.564496 s
mean   = 0.491183 s
median = 0.482096 s
```

První cyklus byl výrazný outlier:

```text
0.564496 s
```

Zbývajících 7 cyklů:

```text
mean = 0.480710 s
range = 0.476055–0.482214 s
```

Tedy prakticky stejný rychlý režim jako dřívější short-OFF série.

## OFF 1 s

```text
N = 8
min    = 0.480891 s
max    = 0.485033 s
mean   = 0.481670 s
median = 0.481016 s
```

## OFF 2 s

```text
N = 8
min    = 0.475711 s
max    = 0.482348 s
mean   = 0.479802 s
median = 0.480563 s
```

## OFF 5 s

Pouze jeden úspěšný frame:

```text
READY = 0.482172 s
```

druhý pokus timeout.

---

# 4. Co V2.1 potvrzuje oproti V2

Úspěšná data z `0.5 / 1 / 2 / 5 s` znovu sedí na rychlý READY režim:

```text
~0.48 s
```

To podporuje předchozí V2 závěr, že krátké OFF intervaly patří do stejné rychlé skupiny.

Z V2 už máme:

```text
OFF 1–10 s   -> READY ~0.48 s
OFF 15–60 s  -> READY ~0.53–0.56 s
```

V2.1 přidává:

```text
OFF 0.5 s -> rovněž převážně ~0.48 s
```

Takže dolní část křivky je ještě lépe potvrzená.

---

# 5. Co V2.1 NEvyřešila

Protože experiment skončil už při druhém 5s cyklu, nemáme nový jemný sweep:

```text
8 / 10 / 11 / 12 / 13 / 14 / 15 / 18 s
```

a nemáme ani plánovaný boot-before-RF sweep:

```text
0–2 s
```

Proto V2.1 **nezpřesnila hranici mezi 10 a 15 s** a **nezměřila skutečnou early-boot boundary**.

Tyto otázky zůstávají pouze z V2:

```text
short OFF <=10 s  -> rychlý režim
long OFF >=15 s   -> pomalejší režim
boot 0.25 s       -> v původním V2 neúspěch
```

---

# 6. Payload recurrence v tomto částečném V2.1 datasetu

Z 25 úspěšných frame:

```text
exact A duplicates:       0
exact B duplicates:       0
exact trailer duplicates: 0
exact full-frame dup:      0
cross-role A == B:         0
```

To není překvapivé vzhledem k malé velikosti datasetu.

Tento částečný V2.1 dataset proto nijak nemění hlavní závěr z předchozí 205-frame cold-boot analýzy:

> První post-boot A/B se nevrací na jeden zjevně fixní stav, ale ve velkém datasetu existují dlouhé 12–16B recurrence a cross-role opakování A/B.

---

# 7. Má smysl V2.1 znovu spouštět?

Pro hlavní cíl výzkumu už **ne**.

Původní klíčová otázka byla:

```text
cold boot -> resetuje se A/B na stejný začátek?
```

Na tu už 205-frame V2 dataset odpověděl dostatečně silně:

```text
nepozorujeme fixní post-reset A/B
```

Jemná hranice mezi 10–15 s je zajímavá hardwarově, ale už není hlavní blokátor pochopení SRAM mailboxu.

Stejně tak detailní early-boot threshold by byl pěkný doplněk, ale sám o sobě nám s největší pravděpodobností nevysvětlí původ A/B ani traileru.

Proto bych kvůli tomuto timeoutu **nepouštěl znovu celou rozsáhlou V2.1 kampaň**.

---

# 8. Aktualizovaný rozhodovací bod

Po V2 + částečné V2.1:

## PHYSICALLY CONFIRMED

- stock MCU vytváří 64B NTAG SRAM mailbox;
- handshake je reprodukovatelně viditelný přes session registry;
- short-OFF režim má READY přibližně `~0.48 s`;
- long-OFF režim z V2 má READY přibližně `~0.53–0.56 s`;
- v jednom V2.1 `OFF=5 s` cyklu RF field existoval, ale stock MCU po >3 s vůbec nezapnulo PTHRU ani SRAM_READY;
- 25 nových V2.1 frame nepřineslo exact A/B restart.

## STRONG INFERENCE

- zařízení má více interních boot/retention/state-machine stavů;
- délka power-off ovlivňuje minimálně časování mailbox obsluhy;
- jednorázový 5s timeout ukazuje, že obsluha RF field není absolutně deterministická pouze podle OFF délky.

## STÁLE NEZNÁMÉ

- přesný původ A;
- přesný původ B;
- význam traileru;
- zda se používá persistentní counter/state;
- přesná fyzická příčina timing změny mezi 10 a 15 s;
- přesná early-boot hranice.

---

# 9. Další doporučený postup

Hlavní NFC experimentální větev bych tímto považoval za dostatečně vytěženou.

Pokud chceme ještě odstranit jednu hardwarovou nejistotu, má smysl pouze jednoduché fyzické ověření:

```text
změřit VDD CC2510 během relé OFF
```

a potvrdit, že při dlouhém OFF skutečně padne do plného power-off/POR stavu.

Jinak bych už čekal na HW debugger.

Až bude dostupný:

```text
1. identifikace debug pinů;
2. pouze CHIP ID / status;
3. žádný unlock;
4. pokud locked -> STOP;
5. pokud readable -> dva nezávislé dumpy;
6. SHA-256 obou dumpů;
7. offline analýza kopie firmware.
```

Hlavní search anchors:

```text
C0 01 01 01
C9 D0 2C AA
64B SRAM write
NTAG I2C komunikace
session/pass-through state
EPD/display state
```

---

# 10. Finální závěr V2.1

V2.1 bohužel **nedoběhla do plánovaného boundary sweepu**.

Přesto přinesla dvě užitečné informace:

1. `OFF=0.5 s` patří stejně jako 1–2 s do rychlého `~0.48 s` režimu;
2. objevil se jeden zvláštní `OFF=5 s` cyklus, ve kterém při aktivním RF fieldu stock MCU během >3 s vůbec nezapnulo pass-through ani nevystavilo SRAM mailbox.

Tento jediný timeout stojí za zaznamenání, ale není důvod kvůli němu znovu rozjíždět stovky NFC cyklů.

## Doporučení zůstává stejné:

# **NFC/cold-boot sběr nyní uzavřít a hlavní pokračování přesunout na bezpečný read-only průzkum CC2510 stock firmwaru po příchodu HW debuggeru.**
