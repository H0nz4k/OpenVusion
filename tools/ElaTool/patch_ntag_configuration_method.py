from __future__ import annotations

from pathlib import Path


METHOD = r"""
    def read_configuration_registers(self) -> dict[int, bytes]:
        \"\"\"Přečte konfigurační registry NTAG I²C Plus přes NFC.

        Stránky:
            0xE8: NC_REG, LAST_NDEF_BLOCK, SRAM_MIRROR_BLOCK, WDT_LS
            0xE9: WDT_MS, I2C_CLOCK_STR, REG_LOCK, RFU

        Používá pouze read-only příkaz READ (0x30).
        \"\"\"
        block = self.read_block(0xE8)

        return {
            0xE8: block[0:4],
            0xE9: block[4:8],
        }

"""


def main() -> None:
    project_root = Path(__file__).resolve().parent
    target = project_root / "src" / "elatec_uid_tool" / "ntag.py"

    if not target.exists():
        raise RuntimeError(f"Nenalezen cílový soubor: {target}")

    text = target.read_text(encoding="utf-8")

    if "def read_configuration_registers(" in text:
        print(f"Metoda už v souboru existuje: {target}")
        return

    marker = "\n    def dump(\n"
    index = text.find(marker)

    if index == -1:
        raise RuntimeError(
            "V ntag.py nebyla nalezena metoda dump(), před kterou se má nová metoda vložit."
        )

    updated = text[:index + 1] + METHOD + text[index + 1:]
    compile(updated, str(target), "exec")
    target.write_text(updated, encoding="utf-8", newline="\n")

    print("Hotovo.")
    print(f"Upraven soubor: {target}")
    print("Nyní spusť:")
    print("python read_ntag_configuration_auto.py")


if __name__ == "__main__":
    main()
