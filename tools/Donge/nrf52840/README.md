# OpenVusion — nRF52840 RF research tooling

Tato část repozitáře obsahuje dvě verzované komponenty:

```text
OpenVusion_RF_Probe/   firmware pro Nordic nRF52840 Dongle
WaterFall/             webová RF/BLE/capture konzole pro Raspberry Pi
```

Aktuální vývojový pár:

```text
OpenVusion RF Probe 0.7.0
WaterFall           0.4.0
```

Poslední fyzicky ověřený firmware je stále `0.6.1`; `0.7.0` je nová zdrojová
verze, která musí projít clean build + fyzickým `test_usb.py` acceptance testem.

## Role komponent

**RF Probe** měří RSSI/energii. Není to SDR ani univerzální packet decoder.

**WaterFall** kombinuje RF survey, focused watch, BLE host-side inventář, TWN4/NFC,
GPIO markery, multi-source capture sessions a offline PCAP/tshark analýzu.

Podrobnosti jsou v samostatných README:

- [`OpenVusion_RF_Probe/README.md`](OpenVusion_RF_Probe/README.md)
- [`WaterFall/README.md`](WaterFall/README.md)

## Verzování

Každá komponenta má vlastní:

```text
VERSION
CHANGELOG.md
README.md
```

Adresář samotný není verzovaný názvem. Release číslo se mění v `VERSION` a
historie je v changelogu.
