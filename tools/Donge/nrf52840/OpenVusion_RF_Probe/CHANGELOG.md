# Changelog — OpenVusion RF Probe

Formát verzí: `MAJOR.MINOR.PATCH`.

## 0.6.1 — 2026-08-11

První verze ověřená na reálném Nordic nRF52840 Dongle + Raspberry Pi 3.

- opraven správný Zephyr 4.4 node label `board_cdc_acm_uart`;
- build verifier vyžaduje právě jeden CDC ACM node;
- USB CDC RX/TX ověřeno přes `PING -> PONG`;
- `INFO` ověřeno na Raspberry Pi;
- `ONCE` vrací 101 RSSI bodů pro 2400–2500 MHz;
- RF vysílání zůstává vypnuté (`RF_TX=DISABLED_BY_DESIGN`);
- kvantitativní RF validace proti známému zdroji je stále otevřená.

## 0.6.0 — 2026-08-11

- odstraněn druhý CDC node z `app.overlay`;
- odstraněn unsolicited startup banner kvůli Linux tty ECHO race;
- zavedena kontrola počtu CDC ACM nodes;
- build neprošel kvůli chybnému node labelu `cdc_acm_uart`.

## 0.5.0 — 2026-08-11

- explicitní USB device-next inicializace;
- oddělení CDC transportu od console/printk;
- laboratorní VID:PID `2fe3:0001`;
- fyzický test odhalil dvě CDC ACM funkce a tty ECHO race.

## 0.4.0 — 2026-08-11

- první interrupt-driven CDC experiment;
- runtime stále vykazoval host write timeout.

## 0.3.x — 2026-08-10/11

- první funkční build/flash experimenty;
- USB enumerace fungovala, datová cesta nikoli.
