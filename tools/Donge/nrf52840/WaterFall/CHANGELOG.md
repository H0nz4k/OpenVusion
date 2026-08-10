# Changelog — WaterFall

Formát verzí: `MAJOR.MINOR.PATCH`.

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
- systemd služba `waterfall.service`;
- instalační adresář `/opt/waterfall`;
- datový adresář `/var/lib/waterfall`.

## 0.2.x — před verzováním WaterFall

Interní OpenVusion RF WebMonitor experimentální větev. Nebyla považována
za stabilní release.
