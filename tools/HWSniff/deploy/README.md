# Nasazení HWSniff GPIO na čisté Raspberry Pi

Cíl: **Pi Zero 2 W** (nebo jiné Pi s Bookworm), **bez displeje**, jen tlačítka / DIP / LED + později TWN4.

## Co balík obsahuje

- `tools/HWSniff` — headless aplikace + systemd unit
- `tools/ElaTool` — připraveno pro alpha2 capture (alpha1 běží na MockCollector)
- `install-on-pi.sh` — bezpečný instalátor

Instalátor **neinstaluje** Xorg, Waveshare, pygame ani framebuffer.

## A) Z Windows: vytvoř balík

V kořeni OpenVusion:

```powershell
python tools\HWSniff\deploy\pack_gpio_bundle.py
```

Výstup:

```
tools/HWSniff/deploy/dist/hwsniff-gpio-1.0-alpha1-YYYYMMDD.tar.gz
tools/HWSniff/deploy/dist/hwsniff-gpio-1.0-alpha1-YYYYMMDD.zip
tools/HWSniff/deploy/dist/hwsniff-gpio-1.0-alpha1-YYYYMMDD.sha256
```

## B) Přenos na Pi

Pi musí mít síť (SSH). Např. z PowerShellu:

```powershell
scp tools\HWSniff\deploy\dist\hwsniff-gpio-*.tar.gz pi@IP_ADRESA:~/
```

Nebo zkopíruj `.zip` na USB a na Pi rozbal.

## C) Instalace na čistém Pi

```bash
# na Pi
cd ~
tar -xzf hwsniff-gpio-*.tar.gz
cd hwsniff-gpio-1.0-alpha1-*   # přesný název podle VERSION

# doporučený bezpečný postup:
sudo bash install-on-pi.sh --no-start   # NEenable — po rebootu hwsniff NEnaběhne
sudo reboot
# po rebootu:
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --gpio-test
sudo systemctl enable --now hwsniff
sudo systemctl status hwsniff
```

Jedním příkazem (včetně GPIO testu před startem služby):

```bash
sudo bash install-on-pi.sh --gpio-test
```

### Volby instalátoru

| Flag | Význam |
|------|--------|
| `--no-start` | Jen nainstaluje; služba **disabled** (reboot ji nespustí) |
| `--enable` | S `--no-start`: enable, ale teď nespouštět |
| `--gpio-test` | Po instalaci LED/tlačítka test; pak enable+start |
| `--skip-apt` | Přeskočí `apt` (offline / už máš balíčky) |
| `--force-unit` | Přepíše existující `/etc/systemd/system/hwsniff.service` |

Existující `/etc/hwsniff/config.json` se **nikdy nepřepisuje**.

## D) Alternativa: git clone na Pi

```bash
sudo apt-get update
sudo apt-get install -y git
git clone <URL_REPO> OpenVusion
cd OpenVusion
sudo bash tools/HWSniff/deploy/install-on-pi.sh --no-start
sudo reboot
```

Starší vstupní bod `tools/HWSniff/install-gpio.sh` volá stejný instalátor.

## Cesty po instalaci

| Cesta | Účel |
|-------|------|
| `/opt/Sniff` | Aplikace + `.venv` |
| `/etc/hwsniff/config.json` | Konfigurace |
| `/var/lib/hwsniff` | Data / captures |
| `/var/log/hwsniff` | Logy |
| `hwsniff.service` | systemd služba |

## Ověření

```bash
systemctl status hwsniff
journalctl -u hwsniff -f

# očekávej READY = zelená LED trvale
# DIP1 ON = Sweet Point mock (G/O/R)
# START z READY = MAIN (žlutá slow)
```

## Aktualizace později

1. Zastav službu: `sudo systemctl stop hwsniff`
2. Znovu zabal / zkopíruj nový balík
3. `sudo bash install-on-pi.sh --no-start` (config zůstane)
4. `sudo systemctl start hwsniff`

Nebo z gitu: `git pull` + znovu `install-on-pi.sh --no-start`.

## Bezpečnost / poznámky

- Služba běží jako uživatel `hwsniff` (skupiny `gpio`, `dialout`).
- **Long STOP (3 s) = reset na MAIN READY**, ne vypnutí. Napájení řeší samostatný hardwarový spínač.
- Alpha1 **nepoužívá** reálný ElaTool capture — ověřuješ GPIO / stavy / LED.
- Po první instalaci vždy jednou **reboot** kvůli skupinám.

## Pi naběhne a hned se vypne (po install + reboot)

Častá příčina u **staršího** balíku: `--no-start` službu stejně **enable** → po rebootu start `hwsniff` → tehdejší long-STOP volal `poweroff`.

**„Deska se spínačem není připojená, jak může být zkrat?“**  
Nemusí to být zkrat na desce. Odpojený pin je *floating*: softwarový pull-up ho má držet v HIGH (nepressed), ale když pull-up naskočí pozdě / selže / pin chvíli plave, active-low logika to může číst jako „STOP držený“. To není fyzický zkrat na tvé desce — je to chování volného GPIO. Nový kód z GPIO **vůbec nevypíná** Pi.

Jiné možné příčiny vypnutí: slabý zdroj / undervoltage při startu služby, nebo ztráta Wi‑Fi (vypadá jako „nejde SSH“, ale Pi běží).

**Přes HDMI + klávesnici:**

```bash
sudo systemctl disable --now hwsniff
systemctl is-enabled hwsniff   # má být disabled
ip -4 addr
dmesg | grep -i voltage || true
```

Pak znovu nasaď **nový** balík s `install-on-pi.sh --no-start`.
