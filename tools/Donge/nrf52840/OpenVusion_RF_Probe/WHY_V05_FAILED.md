# Proč v0.5 vytvořila dva porty a proč se poškodil `PING`

## Dva CDC ACM porty

Fyzický test v0.5 na Raspberry Pi ukázal:

```text
/dev/ttyACM1 ... if00
/dev/ttyACM2 ... if02
```

To jsou dvě CDC ACM funkce.

Příčina: board `nrf52840dongle/nrf52840` už zahrnuje
`boards/common/usb/cdc_acm_serial.dtsi` a tedy vlastní `cdc_acm_uart`.
v0.5 navíc přidala druhý `zephyr,cdc-acm-uart` v `app.overlay`.

v0.6.1 proto `app.overlay` vůbec nemá a používá explicitně board node:

```c
DT_NODELABEL(board_cdc_acm_uart)
```

`verify_build.py` navíc firmware odmítne, pokud generated `zephyr.dts`
neobsahuje právě jeden CDC ACM node.

## `ERR unknown command: OpenVusion RF ePING`

v0.5 posílala okamžitě po DTR startup banner.

Na Linuxu může být krátce mezi `open()` a nastavením termios ještě aktivní
tty ECHO. Část banneru se proto vrátila zpět do RX a parser ji spojil s
následným `PING`.

v0.6.1 neposílá při otevření portu vůbec nic. Protokol je request/response:

```text
PING
PONG v0.6.1
```


## Poznámka k v0.6

První v0.6 build selhal správně při compile-time kontrole, protože jsme
použili neexistující label `cdc_acm_uart`.

Zephyr 4.4.0 board include skutečně pojmenovává node
`board_cdc_acm_uart`. v0.6.1 používá tento přesný label.
