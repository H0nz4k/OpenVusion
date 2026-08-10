import argparse
import hashlib
import re
from pathlib import Path

REQUIRED_Y = [
    "CONFIG_USB_DEVICE_STACK_NEXT=y",
    "CONFIG_USBD_CDC_ACM_CLASS=y",
    "CONFIG_UART_INTERRUPT_DRIVEN=y",
    "CONFIG_UART_LINE_CTRL=y",
]

REQUIRED_NOT_Y = [
    "CONFIG_CDC_ACM_SERIAL_INITIALIZE_AT_BOOT=y",
    "CONFIG_USB_DEVICE_STACK=y",
    "CONFIG_UART_CONSOLE=y",
]

def app_first(paths):
    paths = list(paths)
    paths.sort(key=lambda p: ("OpenVusion" not in str(p), len(str(p))))
    return paths[0] if paths else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build", nargs="?", default="build")
    args = ap.parse_args()
    build = Path(args.build)
    failed = False

    cfg = app_first(build.rglob(".config"))
    if cfg is None:
        raise SystemExit("CHYBA: .config nenalezena")

    text = cfg.read_text(encoding="utf-8", errors="replace")
    print("CONFIG:", cfg)

    for item in REQUIRED_Y:
        ok = item in text
        print(("OK   " if ok else "FAIL "), item)
        failed |= not ok

    for item in REQUIRED_NOT_Y:
        ok = item not in text
        print(("OK   " if ok else "FAIL "), "NOT", item)
        failed |= not ok

    dts = app_first(build.rglob("zephyr.dts"))
    if dts is None:
        print("FAIL zephyr.dts nenalezen")
        failed = True
    else:
        dt = dts.read_text(encoding="utf-8", errors="replace")
        count = len(re.findall(
            r'compatible\s*=\s*"zephyr,cdc-acm-uart"\s*;',
            dt
        ))
        print("DTS:", dts)
        print("CDC ACM node count:", count)

        if count != 1:
            print(
                "FAIL musí být právě JEDEN zephyr,cdc-acm-uart node. "
                "v0.5 měla omylem dva."
            )
            failed = True
        else:
            print("OK   exactly one CDC ACM node")

        if "board_cdc_acm_uart" not in dt:
            print("FAIL board_cdc_acm_uart nenalezen")
            failed = True
        else:
            print("OK   board_cdc_acm_uart present")

    hexf = app_first(build.rglob("zephyr.hex"))
    if hexf is None:
        print("FAIL zephyr.hex nenalezen")
        failed = True
    else:
        digest = hashlib.sha256(hexf.read_bytes()).hexdigest()
        print("HEX:", hexf)
        print("SHA256:", digest)

    if failed:
        raise SystemExit(1)

    print("PASS: OpenVusion RF Probe v0.6.1 build je konzistentní.")
    print("PASS: přes USB má vzniknout právě JEDEN CDC ACM port.")

if __name__ == "__main__":
    main()
