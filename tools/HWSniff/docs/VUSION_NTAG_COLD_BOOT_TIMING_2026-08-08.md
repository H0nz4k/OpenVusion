# VUSION / NTAG I²C Plus — cold-boot timing a retenční hranice

Datum: 2026-08-08

Tento dokument navazuje na:

- `VUSION_NTAG_SESSION_HANDSHAKE_2026-08-07.md`
- `VUSION_NTAG_SRAM_MAILBOX_2026-08-07.md`

Cílem bylo zjistit, zda odpojení hlavního napájení VUSIONu mění chování stock CC2510 firmwaru při následném NFC/RF probuzení a zda lze z cold-bootu získat nový rozlišovací signál pro analýzu živého NTAG SRAM mailboxu.

## Testovaný kus

```text
Rodina:      SES-imagotag / VUSION 2.6
MCU/radio:   TI CC2510F32
NFC:         NTAG I²C Plus 1K
UID:         04367F5A2D7280
Čtečka:      TWN4/B1.64/NCF5.20/PRS1.04
GPIO relé:   BCM17, active-low
```

Experiment byl proveden přes automatizované odpojení hlavní baterie relé modulem. NFC operace zůstaly non-writing; úplný read SRAM je ale, stejně jako v předchozích experimentech, behaviorálně aktivní consume/ack událost NTAG pass-through mailboxu.

## Souhrn kampaně V2

Plánovaná kampaň měla 400 cyklů. Do zastavení na cyklu 206 proběhlo 205 úspěšných capture bez chyby.

Úspěšné skupiny:

```text
00_baseline_start   30× OFF 15 s / boot 10 s
10_off_1s           20× OFF  1 s / boot 10 s
11_off_2s           20× OFF  2 s / boot 10 s
12_off_5s           25× OFF  5 s / boot 10 s
13_off_10s          25× OFF 10 s / boot 10 s
14_off_15s          30× OFF 15 s / boot 10 s
15_off_30s          20× OFF 30 s / boot 10 s
16_off_60s          15× OFF 60 s / boot 10 s
20_baseline_mid     20× OFF 15 s / boot 10 s
```

První test velmi časného RF po bootu:

```text
30_boot_025s        OFF 15 s / boot pouze 0.25 s
```

skončil:

```text
RuntimeError: SRAM_RF_READY timeout
```

Kampaň se tedy korektně zastavila před pokračováním dalších scénářů.

## Nový fyzický nález č. 1 — délka power-off mění READY latenci

Nejvýraznější nový signál není zatím v samotném payloadu, ale v čase, za který stock MCU po přiložení RF pole připraví I²C→NFC SRAM mailbox a nastaví `SRAM_RF_READY`.

### Krátké odpojení: 1–10 sekund

Po OFF 1 s, 2 s, 5 s a 10 s se READY typicky objevuje kolem:

```text
~0.476–0.486 s
```

Velká většina hodnot je velmi těsně kolem:

```text
~0.481–0.482 s
```

To velmi dobře odpovídá dřívějšímu warm/fresh-RF chování (~0.479 s).

### OFF 15 sekund

Po OFF 15 s dochází k jasnému posunu. Typické READY časy jsou:

```text
~0.520–0.541 s
```

s několika prvními / okrajovými hodnotami až kolem:

```text
~0.55–0.56 s
```

### OFF 30–60 sekund

Po OFF 30 s a 60 s se READY stabilizuje převážně kolem:

```text
~0.546–0.566 s
```

Tedy přibližně o 70–80 ms později než u 1–10s power-off scénářů.

## Interpretace retenční hranice

### PHYSICALLY CONFIRMED

Délka odpojení hlavního napájení má reprodukovatelný vliv na čas, za který VUSION po RF aktivaci vystaví `SRAM_RF_READY`.

Prakticky pozorujeme nejméně dva timing režimy:

```text
krátký OFF (1–10 s):  READY ~0.48 s

cold/long OFF
(15–60 s):            READY ~0.53–0.56 s
```

Přechod je v dosavadních datech mezi 10 s a 15 s.

### STRONG INFERENCE

Toto silně ukazuje, že krátké odpojení baterie a delší cold boot nejsou pro stock firmware ekvivalentní stavy.

Možná vysvětlení zahrnují například:

- vybíjení některé napájecí domény nebo kondenzátoru;
- retention/reset stav CC2510 nebo periferií;
- odlišnou inicializační cestu firmwaru po skutečně hlubším power-down;
- čekání na jiný interní hardware/state před vytvořením SRAM frame.

Experiment zatím neurčuje, která z těchto možností je správná.

### DŮLEŽITÝ DŮSLEDEK

Power-off sweep nám poskytl nový **pozorovatelný interní stav** zařízení, i když nemáme přístup ke stock firmwaru:

```text
READY latency
```

lze používat jako vedlejší měřicí kanál při dalších experimentech.

To je nový posun oproti předchozímu testování, kde jsme sledovali hlavně obsah SRAM a session registry.

## Nový fyzický nález č. 2 — RF po 250 ms je příliš brzy

Při:

```text
OFF 15 s
boot bez RF pouze 0.25 s
```

nevznikl ve sledovaném timeout okně očekávaný `SRAM_RF_READY` event.

### PHYSICALLY CONFIRMED

Za těchto konkrétních podmínek stock zařízení nevystavilo mailbox ve stejném časovém režimu jako po standardním 10s boot waitu.

### STRONG INFERENCE

Po skutečném cold startu existuje inicializační okno, během kterého ještě není běžná NFC→MCU/MCU→NFC mailbox obsluha připravena.

To je důležité, protože potvrzuje, že NFC field není jen statický trigger nezávislý na boot stavu MCU. Reakce je navázaná na konkrétní stav běžícího stock firmware.

### Co zatím tvrdit nelze

Z jediného neúspěšného bodu `boot=0.25 s` nelze ještě určit přesnou boot hranici ani říci, zda:

- firmware RF událost během bootu ignoruje;
- událost zaregistruje a zpracuje později;
- NTAG/pass-through je přechodně v jiném stavu;
- timeout testu pouze minul pozdější reakci.

Proto vznikl následný boundary-test V2.1.

## Co tedy z tagu dnes skutečně umíme vyčíst

### Statická data

Přes NTAG RF rozhraní máme stabilně:

- UID `04367F5A2D7280`;
- GET_VERSION `00 04 04 05 02 02 13 03` → NTAG I²C Plus 1K;
- NDEF URI a SES ID `AA2CD0C9`;
- EEPROM / manufacturer-application oblast;
- session/config registry NTAG.

### Živý stav stock MCU

Nepřímo přes NTAG session registry umíme sledovat:

- zapnutí pass-through;
- směr I²C→NFC / NFC→I²C;
- RF field present;
- RF/I²C lock stav;
- `SRAM_RF_READY`;
- okamžik, kdy stock CC2510 připravilo novou zprávu.

### Živý 64B mailbox

Ve stavu `SRAM_RF_READY=1` umíme přečíst kompletní 64B zprávu stock MCU:

```text
0x00..0x0F  pevná hlavička
0x10..0x1F  dynamické pole A
0x20..0x2F  dynamické pole B
0x30..0x3D  14× 00
0x3E..0x3F  dynamický 16bit trailer
```

Pevná část obsahuje SES ID `AA2CD0C9` jako little-endian `C9 D0 2C AA`.

Dynamická 32B oblast není nezávislý fresh RNG: v předchozí 50cyklové studii byly nalezeny přesné mezicyklové shody až 16 B. Konkrétní algoritmus / kryptografický význam ale zatím určen není.

### Nově díky cold bootu

Nyní umíme navíc pozorovat:

- zda zařízení reaguje jako krátce odpojený / retained stav nebo jako hlubší cold-start stav podle READY latence;
- přibližnou hranici změny mezi 10 s a 15 s bez napájení;
- že velmi časný RF trigger 250 ms po cold startu není ekvivalentní standardně nabootovanému zařízení.

## Co cold boot zatím NEPROKÁZAL

Dosavadní V2 konzolový výpis sám o sobě neobsahuje kompletní payloadovou korelační analýzu všech 205 SRAM frame.

Proto zatím nelze zodpovědně tvrdit:

- že dynamická pole A/B po cold bootu začínají vždy stejnou hodnotou;
- že se resetuje konkrétní PRNG seed;
- že existuje pevný challenge-response counter;
- že 15s hranice přímo odpovídá resetu určitého registru nebo RAM;
- že dynamický 16bit trailer je CRC/MAC/counter.

To je nejdůležitější hranice mezi skutečným nálezem a hypotézou.

## Pracovní model po cold-boot kampani

Aktuálně nejlépe sedí tento model:

```text
RF field
  |
  v
stock CC2510 firmware reaguje podle svého aktuálního boot/retention stavu
  |
  +-- warm/short-off cesta  -> SRAM READY ~0.48 s
  |
  +-- deeper-cold cesta     -> SRAM READY ~0.53–0.56 s
  |
  v
MCU vytvoří strukturovaný 64B frame
  |
  v
NTAG I²C Plus PTHRU, I2C -> NFC, SRAM_RF_READY=1
  |
  v
RF-side full SRAM read = consume/ack
```

Cold boot tedy **přinesl nový poznatek**: existuje reprodukovatelná závislost mailbox timing na předchozí době bez hlavního napájení a pravděpodobně více interních inicializačních/retention stavů stock zařízení.

## Další nejhodnotnější experiment

V2.1 by neměla jen generovat další stovky stejných vzorků. Má zacílit dvě hranice:

1. `power-off` mezi 10 a 15 s — najít přechod READY latence;
2. `boot-before-RF` nad 0.25 s — najít nejkratší boot delay, kdy se normální mailbox spolehlivě objeví.

Současně je potřeba korelovat **payload A/B/trailer** s těmito dvěma režimy. Teprve to odpoví na klíčovou otázku, zda deeper cold boot pouze prodlužuje inicializaci, nebo také resetuje / mění generátor dynamické části SRAM frame.

## Bezpečnostní hranice

Výzkum nad jediným fyzickým VUSION kusem musí nadále zůstat nedestruktivní:

- žádný NTAG WRITE;
- žádný config/session WRITE;
- žádné password/auth pokusy;
- při budoucím CC2510 debug připojení nejdříve pouze identifikace/status;
- pokud je debug zamčený, nepoužívat unlock/mass erase;
- případný čitelný firmware nejdříve dumpnout alespoň dvakrát a porovnat hash.
