# Příprava ELATEC TWN4 pro Simple Protocol

## Proč je potřeba jiný firmware

Standardní konfigurovatelná aplikace z AppBlasteru typicky sama čte kartu a posílá hotový výstup. Náš PC program ale potřebuje čtečku aktivně řídit:

```text
GetVersionString
GetDeviceType
GetSupportedTagTypes
SetTagTypes
SearchTag
SetRFOff
```

To poskytuje firmware Simple Protocol označený `PRS`.

## Postup

1. V AppBlasteru ulož aktuální projekt.
2. Pokud máš produkční image, bezpečně jej archivuj.
3. Otevři `Program Firmware Image`.
4. V TWN4 Developer Packu najdi firmware s názvem podobným:

```text
TWN4_Cxvvv_PRSwww.bix
```

5. Ověř kompatibilitu s modelem čtečky.
6. Naprogramuj image.
7. Odpoj a znovu připoj USB.
8. V Správci zařízení zjisti nový COM port.
9. Zavři Serial Port Monitor v AppBlasteru.
10. Spusť:

```powershell
elatec-uid reader-info --port COM13
```

## Očekávaná kontrola

Program pošle:

```text
0004FF\r
```

Čtečka má vrátit verzi obsahující `PRS`, například:

```text
TWN4/.../PRS.../...
```

Pokud nepřijde odpověď:

- je nahraný jiný firmware,
- je vybraný chybný COM port,
- COM port používá jiná aplikace,
- firmware má jiné komunikační nastavení než ASCII / CRC OFF / 9600 baud.

## Návrat k produkční konfiguraci

Po dokončení diagnostiky nahraj zpět původní produkční `.bix`.


## Pomocný příkaz ve verzi 0.1.1

```powershell
elatec-uid prepare-reader --devpack "C:\cesta\k\TWN4DevPack"
```

Příkaz:

- prohledá Developer Pack,
- vypíše všechny `*PRS*.bix`,
- vypíše pravděpodobné programovací nástroje v adresáři `Tools`,
- sám zatím nic neprogramuje.

## Plán automatického nahrání

Automatické nahrání je technicky pravděpodobné, protože toolchain Developer Packu je dostupný i z příkazové řádky. Před implementací je ale nutné získat přesný příkaz a ověřit:

1. identifikaci konkrétního modelu TWN4 ještě před změnou firmware,
2. výběr kompatibilního PRS image,
3. programování přes oficiální nástroj,
4. čekání na odpojení a znovupřipojení USB,
5. nové vyhledání COM portu,
6. kontrolu, že nová verze obsahuje `PRS`,
7. možnost bezpečného návratu k původnímu `.bix`.
