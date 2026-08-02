# Nasazení HWSniff GPIO na čisté Raspberry Pi

Cíl: **Pi Zero 2 W** (nebo jiné Pi s Bookworm), **bez displeje**, jen tlačítka / DIP / LED + později TWN4.

## Deploy z Windows (doporučeno)

Jednou nastav cíl:

```powershell
cd tools\HWSniff\deploy
copy deploy.env.example deploy.env
# uprav HWSNIFF_PI=uzivatel@IP
```

**Denní update kódu** (sync do `/opt/Sniff` + restart služby):

```powershell
cd tools\HWSniff\deploy
.\deploy-to-pi.ps1
# nebo bez deploy.env:
.\deploy-to-pi.ps1 -Target pi@192.168.1.50
```

**První / čistá instalace** na Pi:

```powershell
.\deploy-to-pi.ps1 -Target pi@192.168.1.50 -Mode Full
```

Pak na Pi (nebo přes ssh):

```bash
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --gpio-test
sudo systemctl enable --now hwsniff
```

| Parametr | Význam |
|----------|--------|
| `-Mode Quick` | default — jen kód, bez apt |
| `-Mode Full` | pack + `install-on-pi.sh --no-start` |
| `-NoRestart` | Quick bez `systemctl restart` |
| `-SkipPack` | Full bez nového packu (použije poslední tar v `dist/`) |

Potřebuješ: OpenSSH Client (`ssh`, `scp`), Python, na Pi už jednou doběhl Full install (pro Quick).

## Co balík obsahuje

- `tools/HWSniff` — headless aplikace + systemd unit
- `tools/ElaTool` — připraveno pro alpha2 capture (alpha1 běží na MockCollector)
- `install-on-pi.sh` — bezpečný instalátor

Instalátor **neinstaluje** Xorg, Waveshare, pygame ani framebuffer.

## Ruční pack (volitelné)

```powershell
python tools\HWSniff\deploy\pack_gpio_bundle.py
```

Výstup v `tools/HWSniff/deploy/dist/`.

## Ruční instalace na Pi (USB / bez skriptu)

```bash
cd ~
tar -xzf hwsniff-gpio-*.tar.gz
cd hwsniff-gpio-1.0-alpha1-*

sudo bash install-on-pi.sh --no-start
sudo reboot
sudo -u hwsniff /opt/Sniff/.venv/bin/python -m hwsniff --gpio-test
sudo systemctl enable --now hwsniff
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
