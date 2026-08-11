# WaterFall

**WaterFall** je webová výzkumná konzole pro živé sledování, korelaci a záznam
provozu v pásmu 2,4 GHz v projektu OpenVusion.

**Aktuální verze:** `0.4.0`

WaterFall 0.4.0 není jen „graf RSSI“. Skládá více nezávislých zdrojů dat do
jedné časové osy:

1. **OpenVusion RF Probe / nRF52840** – spektrum a focused RSSI watch;
2. **Bluetooth na Raspberry Pi / BlueZ** – inventář BLE zařízení a advertising reporty;
3. **ELATEC TWN4** – read-only NFC události;
4. **GPIO relay** – přesně časované POWER ON/OFF markery;
5. **PCAP/PCAPNG + tshark** – skutečný packet-level rozbor importovaných capture souborů.

Cílem je workflow podobný Wiresharku: nejdřív zachytit, filtrovat a uložit
pozorování, teprve potom z nich dělat závěry.

---

## Nejdůležitější omezení

WaterFall záměrně rozlišuje **RF energii** a **packet capture**.

### nRF52840 v našem firmware není SDR

OpenVusion RF Probe sekvenčně měří RSSI na zvolených frekvencích. Umí říct:

- kde v pásmu je energie;
- jak je silná;
- zda jde zhruba o úzký nebo široký spektrální jev;
- zda se jev opakuje ve stejném čase jako NFC, power-cycle nebo jiná událost.

Z RSSI samotného ale **nelze určit MAC adresu, zařízení, payload, modulaci ani
protokol**.

### Názvy BLE / Wi-Fi / IEEE 802.15.4 kanálů jsou pouze frekvenční hint

WaterFall u RF kandidátů ukazuje například „BLE adv ch 38“ nebo „802.15.4 ch 15“.
To znamená pouze, že naměřená energie leží na stejné nebo blízké frekvenci.
Neznamená to, že byl daný protokol dekódován.

### BLE Devices je jiný zdroj dat

Seznam BLE zařízení vzniká z Bluetooth adaptéru Raspberry Pi přes BlueZ/Bleak.
Nelze automaticky tvrdit, že konkrétní RF peak z nRF52840 patří konkrétní položce
v BLE seznamu. Je potřeba časová korelace a ideálně packet capture.

### Proprietární VUSION rádio

VUSION s CC2510 nepovažujeme automaticky za BLE ani IEEE 802.15.4. Pro jeho
proprietární RF provoz je WaterFall zatím především spektrální/correlation nástroj.
Packet-level dekódování bude možné až po zjištění skutečných PHY/packet parametrů
nebo s odpovídajícím sniffer profilem.

---

# Architektura

```text
                    +------------------------+
                    |     WaterFall 0.4.0    |
                    | FastAPI + WebSocket UI |
                    +-----------+------------+
                                |
      +-------------------------+--------------------------+
      |                         |                          |
      v                         v                          v
+-------------+          +-------------+            +-------------+
| nRF52840    |          | RPi hci0    |            | PCAP/PCAPNG |
| RF Probe    |          | BlueZ/Bleak |            |   tshark    |
| USB CDC     |          | BLE ADV     |            | packet decode|
+------+------+          +------+------+            +-------------+
       |                        |                          |
       +------------+-----------+--------------------------+
                    |
             Capture Session
                    |
       +------------+-------------+
       |                          |
  TWN4/NFC markers          GPIO POWER markers
```

Primární sestava:

- Raspberry Pi 3;
- Nordic nRF52840 Dongle;
- firmware `OpenVusion RF Probe v0.7.0`;
- volitelně ELATEC TWN4;
- volitelně relay na BCM17.

---

# Záložka Spectrum

## Live Spectrum

Zobrazuje právě poslední sweep v rozsahu 2400–2500 MHz.

Zobrazené metriky:

- `Peak` – frekvence nejsilnějšího bodu;
- `Peak RSSI` – jeho RSSI;
- `Median` – median aktuálního sweepu;
- `Mean` – průměr;
- `Dynamic` – rozdíl nejsilnější/slabší bod;
- `Sweep` – číslo sweepu;
- `Sweep rate` – reálná frekvence příchodu sweepů;
- `RF candidates` – počet heuristických kandidátů;
- `BLE devices` – počet BLE zařízení pozorovaných hostem;
- `Data age` – stáří posledního RF vzorku.

Kliknutí do spektra nastaví frekvenci pro `Focused Watch`.

## Waterfall

Historie sweepů v čase:

```text
X = frekvence
Y = čas
barva = RSSI
```

Je vhodný pro:

- bursty;
- opakující se aktivitu;
- hopping;
- porovnání před/po triggeru;
- hledání frekvencí, které stojí za focused watch.

## Baseline

Tlačítko **Baseline z 10 sweepů** vytvoří pro každý naměřený bin median z
posledních maximálně 10 sweepů.

Pak lze porovnávat:

```text
aktuální RSSI - baseline RSSI
```

Baseline není automatický „detektor protokolu“. Je to referenční pozadí.

## RF candidates

Server při každém sweepu hledá skupiny bodů, které splní současně:

```text
RSSI >= median + threshold_above_median_db
RSSI >= absolute_floor_dbm
```

A sousední body slučuje podle `max_gap_mhz`.

Výstup obsahuje:

- začátek/konec;
- center;
- šířku;
- peak frekvenci;
- peak RSSI;
- delta proti medianu;
- hrubý tvar `narrowband / midband / wideband`;
- frekvenční překryvy známých BLE advertising, IEEE 802.15.4 a Wi-Fi kanálů.

**Je to heuristika, ne classifier.**

## Focused Watch

Firmware 0.7.0 přidává režim:

```text
WATCH START <2400..2500 MHz> <period_ms>
WATCH STOP
```

Místo sweepování celého pásma rádio opakovaně měří jednu frekvenci.

Výstup firmware:

```text
RSSI,<seq>,<device_ms>,<freq_mhz>,<rssi>,<mode>
```

Focused Watch se hodí pro krátké bursty, které by mohl celý sweep minout.

### RSSI sampling mode

Firmware 0.7.0 nabízí:

- `LAST` – poslední RSSI sample po dwell; kompatibilní s chováním 0.6.1;
- `MAX` – nejsilnější sample v průběhu dwell; vhodné pro krátké bursty;
- `AVG` – průměr sample během dwell; vhodné pro stabilnější noise-floor.

### Sweep Step

```text
STEP 1
STEP 2
STEP 5
STEP 10
```

Menší krok = jemnější frekvenční obraz, ale delší sweep.
Větší krok = rychlejší průchod pásmem, ale větší pravděpodobnost, že úzkou aktivitu
mineme.

---

# Záložka Devices

Devices je inventář vytvořený z BLE advertising reportů hostitelského Bluetooth
adaptéru Raspberry Pi.

U zařízení se uchovává:

- BLE adresa;
- první a poslední výskyt;
- počet reportů;
- `name` a `local_name`, pokud je zařízení inzeruje;
- aktuální a nejsilnější RSSI;
- TX power, pokud je inzerován;
- Manufacturer Specific Data;
- Bluetooth SIG Company ID / známý název výrobce, pokud jej známe;
- Service UUID;
- Service Data.

## Filtry Devices

- text: adresa / název / data / výrobce;
- minimum RSSI;
- výrobce;
- Service UUID nebo název služby.

Kliknutím na zařízení se otevře detail.

## BLE START / STOP a čistota RF experimentu

WaterFall 0.4.0 **nespouští BLE scanner automaticky**.

Výchozí konfigurace používá `active` scan, protože je na běžném BlueZ prakticky
nejkompatibilnější. Active scan však může vysílat BLE Scan Request a tím samo
vytvářet 2,4GHz provoz.

Doporučený laboratorní postup:

1. RF background / VUSION experiment → BLE scanner **STOP**;
2. potřebuji inventář okolních BLE zařízení → **BLE START**;
3. po inventarizaci → **BLE STOP**;
4. vrať se k čistému spektrálnímu měření.

Lze nastavit `scan_mode: passive`, ale konkrétní schopnost pasivního scanningu
závisí na BlueZ/kernel backendu. WaterFall při chybě nesmí tiše přepnout do active
režimu, pokud není `allow_active_fallback: true`.

---

# Záložka Packets

Live tabulka `Packets` zatím obsahuje **BLE advertising reporty** z BlueZ/Bleak.

Každý záznam obsahuje podle dostupnosti:

- host timestamp;
- protocol `BLE-ADV`;
- adresu;
- RSSI;
- název;
- TX power;
- Manufacturer Data;
- Service UUIDs;
- Service Data;
- textový raw summary.

Kliknutím na řádek se otevře kompletní JSON detail.

Důležité: nejde o raw on-air Link Layer PDU. Pro frame-level zobrazení použij
PCAP inspector.

---

# Záložka Captures

## WaterFall Capture Session

Toto je preferovaný záznam pro naše experimenty.

`START CAPTURE` vytvoří session s volitelným:

- `Label`;
- `Notes`.

Během záznamu se průběžně ukládá:

```text
rf_sweeps.jsonl
rf_events.jsonl
watch_rssi.jsonl
packets.jsonl
markers.jsonl
config_snapshot.json
```

Po `STOP + ZIP` se doplní:

```text
devices.json
metadata.json
```

a vznikne ZIP session.

Výchozí umístění:

```text
/var/lib/waterfall/sessions/
```

## Browser uložených sessions

WaterFall umí vypsat starší session a přímo v prohlížeči otevřít jejich stream:

- RF events;
- BLE packets;
- Watch RSSI;
- Markers;
- RF sweeps.

Limit pro otevření jednoho streamu je záměrně omezen, aby dlouhý capture
nevyčerpal RAM Raspberry Pi 3.

## Legacy RF CSV

Pro jednoduchou tabulkovou analýzu zůstává:

- Start RF CSV;
- Stop RF CSV;
- download posledního CSV.

CSV obsahuje každý RF bin jako samostatný řádek a summary sweepu.

## Experiment timeline

Samostatný JSONL event recorder uchovává markery například:

```text
SERVER_START
RF_PROBE_ONLINE
NFC_FIELD
NFC_FIELD_OFF
POWER_ON
POWER_OFF
RF_WATCH_START
ANALYZER_SETTINGS
PCAP_IMPORT
USER_MARKER
```

## PCAP / PCAPNG Inspector

Pokud je na Raspberry Pi dostupný `tshark`, lze přes web nahrát:

```text
.pcap
.pcapng
.cap
```

WaterFall pak umí:

- zobrazit seznam packetů;
- `frame.number`;
- timestamp;
- frame length;
- protocol;
- source;
- destination;
- Info;
- aplikovat Wireshark display filter;
- otevřít jeden frame jako plný `tshark -V -x` detail včetně hex bytes;
- původní capture znovu stáhnout.

Příklad display filtru:

```text
btle
wpan
zigbee
frame.number == 42
```

Podporované protokoly nejsou hard-coded WaterFallem – závisí na dissektorech
nainstalovaného Wireshark/tshark a na link-layer typu daného capture souboru.

---

# Jak získat skutečný packet-level capture

Jeden nRF52840 má jeden 2,4GHz radio blok. Náš `OpenVusion RF Probe` jej používá
pro survey/watch. Pokud tentýž dongle přeflashuješ jiným sniffer firmwarem, lze ho
použít i pro jiné specializované profily.

## Bluetooth LE

Nordic poskytuje **nRF Sniffer for Bluetooth LE**, integrovatelný do Wiresharku.
Takto získaný PCAP/PCAPNG můžeš následně otevřít i ve WaterFall PCAP inspectoru.

## IEEE 802.15.4 / Thread / Zigbee

Nordic poskytuje samostatný **nRF Sniffer for 802.15.4** pro nRF52840 / PCA10059.
Capture pak Wireshark dekóduje podle IEEE 802.15.4 a vyšších protokolů, pokud jsou
k dispozici potřebné informace/klíče.

## Proč tyto režimy nejsou zapnuté současně s WaterFall sweepem

Jeden radio frontend nemůže ve stejném okamžiku:

- být na frekvenci 2402 MHz a přijímat packet;
- současně být na 2453 MHz;
- současně sweepovat celé pásmo;
- a ještě sledovat spojení na jiném kanálu.

WaterFall proto používá **více zdrojů a oddělené profily**, místo aby předstíral
schopnost „SDR všeho najednou“.

---

# Ovládání RF Probe 0.7.0

Podporované příkazy:

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
WATCH START <2400..2500> <5..5000 ms>
WATCH STOP
```

Offset `0..100` znamená `2400..2500 MHz`.

---

# Settings / analyzer filtry

Z webu lze za běhu měnit:

- `threshold_above_median_db` – relativní práh;
- `absolute_floor_dbm` – absolutní minimum;
- `max_gap_mhz` – maximální mezera pro sloučení sousedních binů;
- `min_bins` – minimální počet aktivních binů kandidáta.

Tyto parametry nemění rádio; mění pouze detekci/highlighting nad již naměřenými
daty.

---

# Instalace na Raspberry Pi

```bash
cd ~/OpenVusion/tools/Donge/nrf52840/WaterFall
chmod +x install.sh
sudo ./install.sh
```

Installer vytvoří/aktualizuje:

```text
/opt/waterfall
/var/lib/waterfall/captures
/var/lib/waterfall/experiments
/var/lib/waterfall/sessions
/var/lib/waterfall/pcap
/etc/systemd/system/waterfall.service
```

Stav:

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

Po upgrade se existující `config.json` nepřepisuje. Při přechodu z 0.3.x proto
porovnej nové klíče s `config.example.json`, zejména:

```json
"capture_dir"
"pcap_dir"
"analyzer"
"ble_observer"
```

---

# Doporučený config BLE

Pro laboratorní spektrální měření je bezpečné nechat scanner připravený, ale
nespouštět ho automaticky:

```json
"ble_observer": {
  "enabled": true,
  "autostart": false,
  "adapter": "hci0",
  "scan_mode": "active",
  "allow_active_fallback": false
}
```

`active` zde znamená jen BLE observer na Raspberry Pi, nikoli RF Probe.

---

# Mock režim

Pro vývoj UI bez fyzického hardware:

```bash
./run-mock.sh
```

Mock generuje:

- syntetické sweepy;
- širokopásmovou aktivitu;
- krátký úzký peak;
- focused watch;
- testovací BLE advertising reporty.

Mock data jsou jasně označena a nesmí se zaměnit za měření.

---

# REST API – přehled

## Stav

```text
GET  /api/state
GET  /api/health
GET  /api/capabilities
```

## RF

```text
GET  /api/history
GET  /api/watch/history
GET  /api/rf/events
GET  /api/frequency/{freq_mhz}
POST /api/command/{scan_start|scan_stop|once|ping|info|watch_stop}
POST /api/range/{first}/{last}
POST /api/dwell/{ms}
POST /api/step/{mhz}
POST /api/rssi-mode/{mode}
POST /api/watch/start/{freq_mhz}/{period_ms}
```

## BLE

```text
POST /api/ble/start
POST /api/ble/stop
GET  /api/devices
GET  /api/devices/{device_id}
GET  /api/packets
```

## Analyzer

```text
GET  /api/analyzer/settings
POST /api/analyzer/settings
```

## Capture

```text
POST /api/capture/start
POST /api/capture/stop
GET  /api/capture
GET  /api/capture/download
GET  /api/capture/{session_id}/stream/{stream}
```

## Legacy recording / timeline

```text
POST /api/record/start
POST /api/record/stop
GET  /api/record/download
POST /api/experiment/start
POST /api/experiment/stop
GET  /api/experiment/download
POST /api/marker/{label}
```

## Relay

```text
POST /api/relay/on
POST /api/relay/off
```

## PCAP

```text
GET  /api/pcap
POST /api/pcap/upload?filename=...
GET  /api/pcap/{filename}/summary?display_filter=...&limit=...
GET  /api/pcap/{filename}/frame/{frame_number}
GET  /api/pcap/{filename}/download
```

Live data jsou přes:

```text
WS /ws
```

---

# Doporučený experimentální workflow

## A. Validace RF sondy známým zdrojem

1. BLE scanner STOP;
2. udělej background;
3. nastav baseline;
4. známý 2,4GHz zdroj OFF;
5. zdroj ON + aktivita;
6. zdroj OFF;
7. ověř opakovatelnost ve spectrum/waterfall/capture.

## B. Hledání VUSION aktivity

1. začni WaterFall Capture Session;
2. BLE scanner STOP;
3. background;
4. marker nebo NFC/power trigger;
5. sleduj RF candidate;
6. zajímavou frekvenci přepni do Focused Watch;
7. experiment několikrát zopakuj;
8. STOP + ZIP;
9. porovnej `rf_events.jsonl`, `watch_rssi.jsonl`, `markers.jsonl`.

## C. Identifikace okolních BLE zařízení

1. přeruš čisté spektrální měření;
2. BLE START;
3. nech běžet inventarizaci;
4. filtruj RSSI/výrobce/service;
5. otevři detail zařízení/reportu;
6. BLE STOP;
7. až potom pokračuj v čistém RF experimentu.

## D. Packet-level analýza

1. vytvoř capture kompatibilním packet sniffer profilem;
2. ulož `.pcap`/`.pcapng`;
3. importuj do WaterFall;
4. použij Wireshark display filter;
5. otevři detail frame a bytes;
6. závěry koreluj s WaterFall session timeline.

---

# Troubleshooting

## RF Probe offline

```bash
lsusb
ls -l /dev/serial/by-id/
python3 ../OpenVusion_RF_Probe/test_usb.py
```

Očekává se právě jeden CDC ACM port pro OpenVusion RF Probe.

## BLE nejde

```bash
bluetoothctl show
rfkill list
systemctl status bluetooth
```

Pokud je v configu `passive`, může konkrétní BlueZ/kernel odmítnout passive
AdvertisementMonitor. Pro inventarizaci lze přepnout na `active`, ale pak počítej
s možným RF rušením vlastním scan provozem.

## PCAP inspector nefunguje

```bash
tshark --version
```

Bez `tshark` ostatní části WaterFall fungují dál.

## Relay

Před automatickými power-cycle experimenty vždy ručně ověř správnou polaritu a
skutečný stav napájení tagu.

---

# Verze a historie

Aktuální verze: [`VERSION`](VERSION)

Historie změn: [`CHANGELOG.md`](CHANGELOG.md)

Kompatibilní nový firmware: [`../OpenVusion_RF_Probe`](../OpenVusion_RF_Probe/)

---

# Primární technické reference

- Nordic nRF52840 Product Specification: https://docs.nordicsemi.com/r/bundle/ps_nrf52840/
- Nordic nRF Sniffer for Bluetooth LE / nRF Util: https://docs.nordicsemi.com/bundle/nrfutil/page/nrfutil-ble-sniffer/index.html
- Nordic nRF Sniffer for 802.15.4 / PCA10059: https://docs.nordicsemi.com/r/bundle/nrf5_sdk_thread_zigbee/page/nrf802154_sniffer.html
- Zephyr Bluetooth Observer sample: https://docs.zephyrproject.org/latest/samples/bluetooth/observer/README.html
- Bleak Scanner API: https://bleak.readthedocs.io/en/stable/api/scanner.html
