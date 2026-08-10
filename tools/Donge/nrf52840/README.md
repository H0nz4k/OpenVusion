# OpenVusion — nRF52840 RF tooling

Tato část repozitáře obsahuje dva verzované nástroje pro pasivní 2,4GHz RF
výzkum VUSION tagu.

## Aktuální kompatibilní dvojice

| Komponenta | Verze | Úloha |
|---|---:|---|
| [OpenVusion RF Probe](OpenVusion_RF_Probe/) | **0.6.1** | firmware pro Nordic nRF52840 Dongle |
| [WaterFall](WaterFall/) | **0.3.0** | živý webový monitor pro Raspberry Pi |

## Datový tok

```text
2.4 GHz RF
    ↓
Nordic nRF52840 Dongle
OpenVusion RF Probe v0.6.1
    ↓ USB CDC
Raspberry Pi 3
    ↓
WaterFall v0.3.0
    ├─ live spectrum
    ├─ waterfall
    ├─ baseline / Δ
    ├─ CSV capture
    ├─ experiment timeline
    ├─ TWN4/NFC markery
    └─ GPIO relay markery
```

## Stav

USB transport firmware v0.6.1 je fyzicky ověřen na Raspberry Pi:

```text
1× CDC ACM          PASS
PING/PONG           PASS
INFO                PASS
ONCE RSSI sweep     PASS
```

První `ONCE` sweep v rozsahu 2400–2500 MHz byl získán. Další krok je
kalibrační/pozitivní RF kontrola pomocí známého 2,4GHz zdroje před tím, než
budou amplitudy interpretovány jako VUSION provoz.

## Verzování

Každá komponenta má:

- stabilní adresář bez čísla verze;
- soubor `VERSION`;
- `CHANGELOG.md`;
- vlastní `README.md`.

Historické poznámky a výzkumné výsledky zůstávají v dokumentaci projektu.
