import argparse
import hashlib
import re
from pathlib import Path

FW_VERSION = "0.7.0"
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


def source_checks(project_root: Path) -> bool:
    failed = False
    source = project_root / "src" / "main.c"
    if not source.exists():
        print("FAIL src/main.c nenalezen")
        return True
    text = source.read_text(encoding="utf-8", errors="replace")
    checks = {
        f'FW_NAME "OpenVusion_RF_Probe_v{FW_VERSION}"': f'#define FW_NAME "OpenVusion_RF_Probe_v{FW_VERSION}"' in text,
        "WATCH command": "WATCH START" in text and "WATCH STOP" in text,
        "RSSI MODE command": "RSSI MODE" in text,
        "STEP command": "STEP 1|2|5|10" in text,
        "focused RSSI output": '"RSSI,%u,%lld,%u,%d,%s' in text,
    }
    for label, ok in checks.items():
        print(("OK   " if ok else "FAIL "), "SOURCE", label)
        failed |= not ok

    # TXEN may appear in explanatory comments; require no actual register write.
    tx_patterns = [
        r"NRF_RADIO\s*->\s*TASKS_TXEN\s*=",
        r"nrf_radio_task_trigger\s*\([^\n]*NRF_RADIO_TASK_TXEN",
    ]
    tx_found = any(re.search(pattern, text) for pattern in tx_patterns)
    print(("FAIL " if tx_found else "OK   "), "SOURCE no RF TXEN operation")
    failed |= tx_found
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build", nargs="?", default="build")
    ap.add_argument("--source-only", action="store_true", help="zkontroluje invariants zdrojů bez NCS build adresáře")
    args = ap.parse_args()
    build = Path(args.build)
    root = Path(__file__).resolve().parent
    failed = source_checks(root)
    if args.source_only:
        if failed:
            raise SystemExit(1)
        print(f"PASS: OpenVusion RF Probe v{FW_VERSION} source-only invariants.")
        return

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
        count = len(re.findall(r'compatible\s*=\s*"zephyr,cdc-acm-uart"\s*;', dt))
        print("DTS:", dts)
        print("CDC ACM node count:", count)
        if count != 1:
            print("FAIL musí být právě JEDEN zephyr,cdc-acm-uart node.")
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
    print(f"PASS: OpenVusion RF Probe v{FW_VERSION} build je konzistentní.")
    print("PASS: přes USB má vzniknout právě JEDEN CDC ACM port.")
    print("PASS: ve zdrojovém kódu nebyla nalezena RF TXEN operace.")


if __name__ == "__main__":
    main()
