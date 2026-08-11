# Changelog — WaterFall

Formát verzí: `MAJOR.MINOR.PATCH`.

## 0.4.0 — 2026-08-11

První „Wireshark-like“ výzkumná konzole WaterFall.

### RF

- kompatibilita s OpenVusion RF Probe v0.7.0;
- live spectrum 2400–2500 MHz;
- waterfall;
- baseline;
- heuristické RF candidates;
- frekvenční hinty BLE advertising / IEEE 802.15.4 / Wi-Fi;
- nový Focused Watch na jedné frekvenci;
- graf watch RSSI v čase;
- ovládání sweep `STEP 1/2/5/10 MHz`;
- ovládání `RSSI MODE LAST/MAX/AVG`;
- runtime nastavení analyzer threshold/floor/gap/min-bins.

### Devices / BLE

- nový host-side BLE observer přes Raspberry Pi / BlueZ / Bleak;
- BLE START / STOP z UI;
- autostart je výchozím configem vypnutý, aby BLE scan nekontaminoval čistý RF experiment;
- inventář BLE zařízení;
- RSSI, first/last seen, count;
- local name/name;
- manufacturer data + známé company ID;
- service UUID / service data;
- filtry zařízení a reportů;
- detail každého zařízení/reportu.

### Capture

- nový multi-source WaterFall Capture Session;
- RF sweep JSONL;
- RF event JSONL;
- focused watch JSONL;
- BLE packet/report JSONL;
- marker JSONL;
- config snapshot;
- device snapshot;
- metadata;
- automatický ZIP po stop;
- browser uložených session a jejich streamů;
- zachován rychlý RF CSV recorder;
- zachován experiment timeline recorder.

### PCAP / Wireshark workflow

- PCAP/PCAPNG/CAP knihovna;
- upload přes web;
- offline decode pomocí tshark;
- Wireshark display filter;
- packet table;
- detail frame přes `tshark -V -x` včetně bytes;
- download původního capture.

### UI

- záložky Spectrum / Devices / Packets / Captures / Settings;
- capability/status badges;
- filtry;
- detailní dokumentace interpretace a omezení.

## 0.3.0 — 2026-08-11

První verzovaná verze pod názvem **WaterFall**.

- kompatibilita s OpenVusion RF Probe v0.6.1;
- auto-detekce RF sondy podle VID:PID/serial;
- živé spektrum 2400–2500 MHz;
- waterfall historie;
- heat-grid všech 101 frekvenčních bodů;
- top frekvence, peak, median, mean a dynamický rozsah;
- trend peak/noise;
- baseline z posledních 10 sweepů;
- CSV recording;
- experiment JSONL markery;
- TWN4 read-only watcher;
- GPIO relay BCM17 active-low;
- systemd služba `waterfall.service`.

## 0.2.x — před verzováním WaterFall

Interní OpenVusion RF WebMonitor experimentální větev. Nebyla považována za stabilní release.
