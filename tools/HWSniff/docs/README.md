# HWSniff documentation

Current reference documents:

- [`HARDWARE_V2.md`](HARDWARE_V2.md) — Raspberry Pi Zero 2 W / GPIO / state machine hardware notes.
- [`TAG_TECHNOLOGIES.md`](TAG_TECHNOLOGIES.md) — tag-family and teardown notes. Some SOLUM sections are historical and predate physical FeliCa confirmation.
- [`FIELD_CAPTURES.md`](FIELD_CAPTURES.md) — selected physical field captures. Early SOLUM entries describe the state before FeliCa-native probing was implemented.
- [`SOLUM_FELICA_CONFIRMED.md`](SOLUM_FELICA_CONFIRMED.md) — **current authoritative SOLUM NFC findings**, including physical FeliCa confirmation, NFC Forum Type 3 / `0x12FC`, public service `0x000B`, Attribute Block decode, full public dump, blocks 54–56, 120-second stability test, provisioning/RF hypotheses and read-only helper scripts.

For SOLUM NFC classification, prefer `SOLUM_FELICA_CONFIRMED.md` over older `probable_felica_type3` wording.
