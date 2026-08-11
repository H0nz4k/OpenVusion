# OpenVusion RF Probe

Firmware pro **Nordic nRF52840 Dongle (PCA10059)** používaný WaterFallem jako
pasivní 2,4GHz RSSI/energy survey a focused-watch sondu.

**Aktuální zdrojová verze:** `0.7.0`

> `0.7.0` je nová verze připravená pro WaterFall 0.4.0. V tomto balíku prošla
> statickými kontrolami zdrojů, ale nebyla v prostředí asistenta zkompilována NCS
> toolchainem ani fyzicky flashnuta. **Poslední fyzicky ověřený fallback je 0.6.1.**
> Před použitím 0.7.0 proto proveď `build_clean.ps1` a `test_usb.py` podle postupu
> níže.

---

## Co firmware dělá

- USB CDC ACM textové rozhraní;
- sekvenční RSSI survey 2400–2500 MHz;
- nastavitelný rozsah;
- nastavitelný dwell;
- nastavitelný frekvenční krok;
- tři způsoby RSSI sample během dwell;
- focused watch jedné frekvence;
- žádný packet decoder;
- žádný záměrný RF TX.

Firmware je navržen jako **měřicí sonda**, ne jako univerzální SDR.

---

# Novinky 0.7.0

## STEP

```text
STEP 1
STEP 2
STEP 5
STEP 10
```

Určuje frekvenční krok sweepu v MHz.

Například při:

```text
RANGE 0 100
STEP 5
```

se měří:

```text
2400, 2405, 2410, ... 2500 MHz
```

Trade-off:

- 1 MHz = nejlepší frekvenční rozlišení, nejdelší sweep;
- 10 MHz = nejrychlejší sweep, ale může minout úzký burst.

## RSSI MODE

```text
RSSI MODE LAST
RSSI MODE MAX
RSSI MODE AVG
```

### LAST

Poslední RSSI hodnota po dwell. Zachovává princip chování 0.6.1.

### MAX

Během dwell se každou přibližně 1 ms vezme RSSI a vrací se nejsilnější vzorek.
Je vhodnější pro krátkou burst aktivitu.

### AVG

Vrátí průměr vzorků během dwell. Je vhodný pro stabilnější pozorování noise-floor.

## WATCH

```text
WATCH START <freq_mhz> <period_ms>
WATCH STOP
```

Rozsahy:

```text
freq_mhz  = 2400..2500
period_ms = 5..5000
```

Příklad:

```text
WATCH START 2453 20
```

Firmware přestane sweepovat celé pásmo a opakovaně vrací:

```text
RSSI,<seq>,<device_ms>,<freq_mhz>,<rssi>,<mode>
```

Například:

```text
RSSI,18,123456,2453,-67,MAX
```

`SCAN START` vypíná WATCH a `WATCH START` vypíná SCAN.

Focused Watch je důležitý pro jevy kratší než celý sweep.

---

# Příkazy

```text
PING
INFO
HELP
ONCE
SCAN START
SCAN STOP
RANGE <0..100> <0..100>
DWELL <1..100>
STEP 1|2|5|10
RSSI MODE LAST|MAX|AVG
WATCH START <2400..2500> <5..5000>
WATCH STOP
```

`RANGE` používá offset od 2400 MHz:

```text
RANGE 0 100  => 2400..2500 MHz
RANGE 37 60  => 2437..2460 MHz
```

---

# Výstup SWEEP

```text
SWEEP,<sweep_no>,<device_ms>,2400:-93,2401:-97,...
```

Při větším `STEP` jsou přítomny pouze skutečně změřené frekvence.

Pokud měření jednoho bodu selže:

```text
2453:ERR-110
```

---

# INFO 0.7.0

Kromě USB stavu obsahuje například:

```text
FW=OpenVusion_RF_Probe_v0.7.0
BOARD=nrf52840dongle/nrf52840
USB_CDC_COUNT=1
RF_TX=DISABLED_BY_DESIGN
RANGE=0..100
FREQ=2400..2500MHz
DWELL_MS=4
STEP_MHZ=1
RSSI_MODE=LAST
SCAN=0|1
WATCH=0|1
WATCH_FREQ_MHZ=...
WATCH_PERIOD_MS=...
```

---

# RF bezpečnost návrhu

Zdroj používá receive/RSSI cestu a obsahuje kontrolu, že není použita skutečná
RF `TXEN` operace.

`verify_build.py` kromě USB konfigurace kontroluje i zdrojové vlastnosti 0.7.0.

Poznámka: text `TASKS_TXEN` se může objevit v komentáři vysvětlujícím záměr;
verifier hledá skutečný zápis/trigger TXEN, ne pouhý komentář.

---

# USB architektura

Stejně jako ověřená 0.6.1:

```text
Zephyr USB device-next
        |
        +-- explicit USBD device/configuration
        |
        +-- board_cdc_acm_uart
                |
                +-- RX: interrupt-driven UART API
                +-- TX: polling UART API z thread context
```

Board `nrf52840dongle/nrf52840` poskytuje jediný CDC ACM node.
Projekt proto nepřidává druhý CDC node přes overlay.

Po flashi má Linux/RPi vidět právě **jeden** OpenVusion CDC ACM port.

Laboratorní identifikace:

```text
VID:PID 2fe3:0001
Product OpenVusion RF Probe v0.7.0
```

Tento VID/PID je laboratorní/research nastavení, ne identifikátor pro komerční
produkt.

---

# Statická kontrola zdroje

Bez NCS toolchainu lze ověřit základní invariants:

```bash
python3 verify_build.py --source-only
```

Tato kontrola ověřuje verzi, nové WATCH/STEP/RSSI MODE příkazy a že zdroj neobsahuje skutečnou RF TXEN operaci. Nenahrazuje NCS build.

# Build — Windows / nRF Connect SDK 3.4.0

Použij NCS terminal ve složce firmware:

```powershell
.\build_clean.ps1
```

Skript:

1. odstraní starý `build`;
2. provede čistý `west build`;
3. spustí `verify_build.py`;
4. build odmítne jako validní, pokud verifier nenajde správnou USB konfiguraci,
   právě jeden CDC node nebo nové source invariants.

Target:

```text
nrf52840dongle/nrf52840
```

Očekávaný závěr:

```text
PASS: OpenVusion RF Probe v0.7.0 build je konzistentní.
PASS: přes USB má vzniknout právě JEDEN CDC ACM port.
PASS: ve zdrojovém kódu nebyla nalezena RF TXEN operace.
BUILD + VERIFY PASS
```

Pokud tento závěr nevznikne, firmware neflashovat.

---

# Flash

Použij tovární Nordic DFU bootloader a nRF Connect Programmer stejně jako u
ověřené 0.6.1.

Typický HEX po build bude pod:

```text
build/<app>/zephyr/zephyr.hex
```

Před Write vždy ověř, že flashuješ výstup právě z 0.7.0 clean buildu.

---

# Acceptance test na Raspberry Pi

Po flashi:

```bash
python3 test_usb.py
```

Test ověří:

1. právě jeden `2fe3:0001` CDC port;
2. žádný unsolicited startup text;
3. `PING -> PONG v0.7.0`;
4. `INFO`;
5. `STEP 5` a návrat `STEP 1`;
6. `RSSI MODE MAX` a návrat `LAST`;
7. krátký `WATCH START 2453 25`;
8. alespoň jeden `RSSI,...` sample;
9. `WATCH STOP`.

Pouze základní USB test:

```bash
python3 test_usb.py --basic-only
```

Případně explicitní port:

```bash
python3 test_usb.py /dev/ttyACM1
```

Teprve po PASS považuj 0.7.0 za fyzicky přijatou verzi.

---

# Rychlý manuální test

Po otevření CDC:

```text
PING
INFO
ONCE
RSSI MODE MAX
WATCH START 2453 20
WATCH STOP
SCAN START
```

---

# WaterFall

Firmware 0.7.0 je připraven pro:

```text
../WaterFall 0.4.0
```

WaterFall umí nový focused watch, step a RSSI sampling mode ovládat přímo z webu.

---

# Packet capture: co tento firmware neumí

nRF52840 hardware podporuje více 2,4GHz režimů, ale tento konkrétní firmware
záměrně nedělá:

- BLE Link Layer packet sniffer;
- IEEE 802.15.4 packet sniffer;
- Wi-Fi capture;
- univerzální CC2510/VUSION packet decoder.

Pro známé standardní protokoly je přesnější použít specializovaný sniffer profil
a výsledný PCAP otevřít ve WaterFall/tshark/Wireshark.

---

# Stav verzí

## 0.7.0

Zdrojová verze pro WaterFall 0.4.0. Vyžaduje nový fyzický acceptance test.

## 0.6.1

Poslední fyzicky ověřená verze:

```text
USB enumerace             PASS
1× CDC ACM                 PASS
PING / INFO                PASS
ONCE                       PASS
101 bodů 2400..2500 MHz    PASS
```

Pokud by 0.7.0 při build/runtime testu selhala, vrať se na Git commit s 0.6.1 a
nepokračuj v RF interpretaci na neověřeném firmware.

Aktuální verze je v [`VERSION`](VERSION), historie v [`CHANGELOG.md`](CHANGELOG.md).
