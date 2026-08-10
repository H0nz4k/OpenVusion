# WaterFall

**WaterFall** je webová aplikace pro živou vizualizaci a záznam 2,4GHz RF
výzkumu v projektu OpenVusion.

**Aktuální verze:** `0.3.0`

Primární hardware:

- Raspberry Pi 3;
- Nordic nRF52840 Dongle s firmwarem
  [`OpenVusion RF Probe v0.6.1`](../OpenVusion_RF_Probe/);
- volitelně ELATEC TWN4;
- volitelně GPIO relay pro řízení napájení testovaného tagu.

## Co zobrazuje

- živé RSSI spektrum 2400–2500 MHz;
- waterfall;
- všech 101 aktuálních 1MHz bodů;
- Top 12 nejsilnějších frekvencí;
- peak frekvenci a RSSI;
- median noise a mean RSSI;
- dynamický rozsah;
- počet výrazných bodů nad medianem;
- rychlost sweepů;
- trend peak/noise;
- baseline a delta proti baseline;
- časované experimentální markery.

## Ovládání RF sondy

Z webu lze posílat:

```text
SCAN START
SCAN STOP
ONCE
PING
INFO
RANGE
DWELL
```

WaterFall očekává OpenVusion RF Probe přes USB CDC. Výchozí konfigurace
auto-detekuje laboratorní zařízení:

```text
VID:PID 2fe3:0001
SN      A66E2D26F8A4CB87
```

Sériový port tedy není vázán na konkrétní `/dev/ttyACM*`.

## Záznam

WaterFall umí:

- CSV záznam jednotlivých RF bodů;
- JSONL experiment timeline;
- download posledního záznamu přes web.

Výchozí data:

```text
/var/lib/waterfall/captures
/var/lib/waterfall/experiments
```

## TWN4 / NFC

TWN4 watcher je read-only. Pokud je dostupný ElaTool, WaterFall umí zaznamenat:

```text
NFC_READER_ONLINE
NFC_FIELD
NFC_FIELD_OFF
NFC_ERROR
```

Výchozí očekávaná cesta čtečky:

```text
/dev/serial/by-id/usb-OEM_TWN4_B1.64_NCF5.20_PRS1.04-if00
```

## GPIO relay

Výchozí konfigurace:

```text
BCM17
active-low
```

Web nabízí POWER ON/OFF a zapisuje timestampované markery.

Před automatickými cykly vždy nejdřív ručně ověř správnou polaritu relé.

## Instalace na Raspberry Pi

```bash
chmod +x install.sh
sudo ./install.sh
```

Instalace vytvoří:

```text
/opt/waterfall
/var/lib/waterfall
waterfall.service
```

Stav služby:

```bash
sudo systemctl status waterfall --no-pager
```

Log:

```bash
journalctl -u waterfall -f
```

Web:

```text
http://<IP_RPI>:8088/
```

Config:

```text
/opt/waterfall/config.json
```

## Rychlý běh bez instalace

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json
WATERFALL_CONFIG=$PWD/config.json .venv/bin/python run_server.py
```

## Mock režim

```bash
./run-mock.sh
```

Mock režim slouží jen pro kontrolu UI bez fyzické RF sondy.

## Doporučený RF experiment

1. ověř `PROBE: ONLINE`;
2. nech několik desítek sweepů vytvořit pozadí;
3. nastav baseline;
4. zapni známý 2,4GHz zdroj;
5. ověř reprodukovatelný rozdíl OFF → ON → OFF;
6. až poté interpretuj VUSION měření.

WaterFall je vizualizace **RSSI/energy survey**, nikoli SDR ani packet decoder.
Každý frekvenční bod je měřen sekvenčně.

## Verze

Aktuální verze je v [`VERSION`](VERSION), historie v
[`CHANGELOG.md`](CHANGELOG.md).
