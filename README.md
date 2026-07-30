# OpenVusion Research

> Reverse engineering, dokumentace a vývoj open-source nástrojů pro elektronické cenovky **SES-imagotag / Vusion GU140**.

---

## O projektu

Tento projekt vznikl jako technický výzkum elektronických cenovek **SES-imagotag Vusion GU140**, které se běžně používají jako elektronické cenovky (ESL – Electronic Shelf Labels).

Cílem není vytvářet nástroje pro útoky na cizí infrastrukturu ani obcházet zabezpečení obchodních systémů.

Naopak.

Cílem je pochopit princip fungování zařízení, zdokumentovat jeho hardware a komunikační rozhraní a vytvořit otevřenou dokumentaci, která dnes prakticky neexistuje.

Projekt je prováděn na **legálně vlastněném zařízení**, které bylo zakoupeno mimo provozní infrastrukturu.

---

# Proč tento projekt vznikl?

O cenovkách SES-imagotag existuje velmi málo veřejných technických informací.

Přesto obsahují velmi zajímavý hardware:

- e-paper displej
- Sub-GHz rádio
- NFC rozhraní
- vlastní MCU
- optické prvky
- velmi úsporné napájení

Je škoda, že po vyřazení končí většina těchto zařízení jako elektroodpad.

Projekt si klade za cíl zjistit, zda je možné tato zařízení znovu využít pro vlastní aplikace.

---

# Hlavní cíle

## 1. Zdokumentovat hardware

- fotografie
- PCB
- použité čipy
- napájení
- displej
- optické prvky

---

## 2. Zdokumentovat NFC

- identifikace NFC čipu
- mapa paměti
- registrů
- bezpečnostních mechanismů
- I²C bridge

Použité nástroje:

- Flipper Zero
- Elatec TWN4
- NXP nástroje

---

## 3. Zdokumentovat RF komunikaci

Zjistit například:

- pracovní frekvenci
- modulaci
- datovou rychlost
- strukturu rámců
- synchronizační slova
- adresování zařízení

Použité nástroje:

- Flipper Zero
- CC1101
- RTL-SDR (plánováno)

---

## 4. Zdokumentovat firmware

- identifikace MCU
- boot proces
- debug rozhraní
- možnosti obnovy

---

## 5. Vytvořit vlastní gateway

Dlouhodobým cílem je vytvořit open-source gateway umožňující komunikaci s vlastněnými cenovkami.

Možné platformy:

- ESP32
- Raspberry Pi
- Linux
- SDR
- CC1101

---

# Struktura repozitáře

```
docs/
```

Ověřená dokumentace.

---

```
captures/
```

Surové zachycené rámce.

- NFC
- TWN4
- SubGHz

---

```
images/
```

Fotografie zařízení.

---

```
notes/
```

Pracovní poznámky.

Sem patří hypotézy, nápady a průběžné poznatky.

---

```
references/
```

Dokumentace výrobců.

---

```
tools/
```

Pomocné utility a skripty.

---

# Pravidla projektu

Projekt rozlišuje dvě úrovně informací.

## Ověřená fakta

Jsou uložena v adresáři `docs`.

Musí být potvrzena:

- měřením
- dokumentací výrobce
- nebo opakovaným experimentem.

---

## Hypotézy

Patří pouze do `notes`.

Nikdy nejsou vydávány za ověřená fakta.

---

# Bezpečnost

Během výzkumu se provádí pouze bezpečné experimenty na vlastněném zařízení.

Dokud nebude plně zdokumentována struktura paměti a význam registrů:

- neprovádí se zápis do EEPROM,
- nemění se konfigurace NFC,
- neupravuje se firmware.

Veškeré experimenty probíhají na zařízení vlastněném autorem projektu.

---

# Aktuální stav

✔ Identifikováno zařízení

✔ Identifikován NFC čip

✔ Ověřen UID

✔ Ověřeny ATQA a SAK

✔ Zprovozněn Elatec TWN4

🔄 Analýza NFC komunikace

🔄 Analýza RF komunikace

⏳ Analýza PCB

⏳ Analýza firmware

---

# Budoucí cíle

- kompletní mapa hardwaru
- dokumentace NFC
- dokumentace RF protokolu
- open-source gateway
- vlastní firmware (pokud bude technicky možný)
- knihovna pro komunikaci s GU140
- vlastní editor obrázků pro e-paper displej

---

# Licence

Projekt slouží výhradně pro výzkum, vzdělávání, interoperabilitu a dokumentaci hardwaru.

Autoři nenesou odpovědnost za použití projektu v rozporu s platnými zákony nebo podmínkami provozovatelů zařízení.