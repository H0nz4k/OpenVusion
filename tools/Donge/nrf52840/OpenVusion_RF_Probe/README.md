# OpenVusion RF Probe

Firmware pro **Nordic nRF52840 Dongle (PCA10059)** používaný jako pasivní
2,4GHz RSSI/energy survey sonda v projektu OpenVusion.

**Aktuální verze:** `0.6.1`

## Stav ověření

Ověřeno na:

- Nordic nRF52840 Dongle;
- nRF Connect SDK 3.4.0;
- Zephyr 4.4.0;
- target `nrf52840dongle/nrf52840`;
- Raspberry Pi 3 jako USB host.

Ověřené body:

```text
USB enumerace                  PASS
právě 1× CDC ACM              PASS
PING -> PONG                   PASS
INFO                           PASS
ONCE -> 101 RSSI bodů          PASS
2400..2500 MHz                 PASS
RF TX                          DISABLED BY DESIGN
```

První fyzický `ONCE` sweep byl úspěšně získán. RSSI/energy survey zatím
**není považován za kvantitativně zkalibrovaný**; před interpretací VUSION
provozu se má udělat pozitivní kontrola známým 2,4GHz zdrojem.

## USB architektura

Firmware používá nový Zephyr USB device stack:

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

Board `nrf52840dongle/nrf52840` už poskytuje jediný CDC ACM node. Projekt
proto záměrně **nemá `app.overlay` s dalším CDC ACM**.

Linux/RPi má po správném flashi vidět právě jeden OpenVusion sériový port.

## RF model

RF část je pouze pasivní survey:

- rozsah 2400–2500 MHz;
- krok 1 MHz;
- výchozí dwell 4 ms;
- RADIO se inicializuje až při `ONCE` nebo `SCAN START`;
- ve firmware není použit `NRF_RADIO->TASKS_TXEN`.

Důležité: nejde o SDR ani packet decoder. Jednotlivé frekvence se měří
sekvenčně, takže krátký burst může být zachycen pouze v jednom nebo několika
bodech jednoho sweepu.

## Příkazy

```text
PING
INFO
HELP
ONCE
SCAN START
SCAN STOP
RANGE <0..100> <0..100>
DWELL <1..100>
```

Příklad:

```text
PING
PONG v0.6.1
```

`ONCE`:

```text
SWEEP,<n>,<device_ms>,2400:-93,2401:-97,...,2500:-101
```

## Build

Použij nRF Connect SDK 3.4.0 terminal:

```powershell
.\build_clean.ps1
```

Verifier musí na konci potvrdit:

```text
CDC ACM node count: 1
OK   exactly one CDC ACM node
OK   board_cdc_acm_uart present
PASS: OpenVusion RF Probe v0.6.1 build je konzistentní.
BUILD + VERIFY PASS
```

Pokud verifier nedá `PASS`, firmware neflashovat.

## Flash

Target:

```text
nrf52840dongle/nrf52840
```

Výstup:

```text
build\OpenVusion_RF_Probe_v0.6.1\zephyr\zephyr.hex
```

Použij tovární Nordic DFU bootloader a `Write`. Nepoužívej `Erase all`,
pokud k tomu není konkrétní důvod.

## Acceptance test na Raspberry Pi

```bash
python3 test_usb.py
```

Očekávané minimum:

```text
PONG v0.6.1
...
PASS: OpenVusion RF Probe v0.6.1 USB CDC RX/TX funguje.
```

První RF test:

```text
ONCE
```

## Collector

```bash
python3 rf_collect.py
```

Pro živou vizualizaci a záznam používej sesterskou aplikaci
[`../WaterFall`](../WaterFall/).

## Verze

Aktuální verze je v souboru [`VERSION`](VERSION). Historie změn je v
[`CHANGELOG.md`](CHANGELOG.md).
