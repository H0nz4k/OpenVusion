from __future__ import annotations

from .protocol import ElatecError, enumerate_ports

PortInfo = tuple[str, str, str]


def is_probable_elatec_port(port: PortInfo) -> bool:
    device, description, hwid = port
    text = f"{device} {description} {hwid}".upper()
    return any(token in text for token in ("VID:PID=09D8:", "VID_09D8", "ELATEC", "TWN4"))


def probable_elatec_ports(ports: list[PortInfo]) -> list[PortInfo]:
    return [port for port in ports if is_probable_elatec_port(port)]


def recommended_port_index(ports: list[PortInfo]) -> int | None:
    candidates = probable_elatec_ports(ports)
    return ports.index(candidates[0]) if len(candidates) == 1 else None


def print_ports() -> list[PortInfo]:
    ports = enumerate_ports()
    if not ports:
        print("Nebyl nalezen žádný sériový port.")
        return []
    recommended = recommended_port_index(ports)
    print("Dostupné sériové porty:\n")
    for index, (device, description, hwid) in enumerate(ports, start=1):
        marker = "   <-- pravděpodobně ELATEC" if recommended == index - 1 else ""
        print(f"  {index}. {device}  {description}{marker}")
        if hwid:
            print(f"     HWID: {hwid}")
        print()
    return ports


def resolve_port_selection(
    entered: str,
    ports: list[PortInfo],
    default_index: int | None,
) -> tuple[str, str | None]:
    value = entered.strip()
    if not value:
        if default_index is None:
            raise ElatecError("Port nebyl vybrán.")
        return ports[default_index][0], None
    for device, _, _ in ports:
        if value.upper() == device.upper():
            return device, None
    if value.isdigit():
        number = int(value)
        if 1 <= number <= len(ports):
            return ports[number - 1][0], None
        candidate = f"COM{number}"
        for device, _, _ in ports:
            if candidate.upper() == device.upper():
                return device, f"Zadané číslo {number} interpretuji jako {device}."
    raise ElatecError("Neplatný výběr portu.")


def _prompt_for_port(ports: list[PortInfo], heading: str) -> str:
    print(heading, "\n")
    for index, (device, description, hwid) in enumerate(ports, start=1):
        print(f"  {index}. {device}  {description}")
        if hwid:
            print(f"     HWID: {hwid}")
        print()
    device, note = resolve_port_selection(
        input(f"Vyber číslo položky 1-{len(ports)}: "), ports, None
    )
    if note:
        print(note)
    print(f"Vybraný port: {device}")
    return device


def select_port_interactively(timeout: float = 1.2) -> str:
    del timeout
    ports = enumerate_ports()
    if not ports:
        raise ElatecError("Nebyl nalezen žádný sériový port.")
    candidates = probable_elatec_ports(ports)
    if len(candidates) == 1:
        device, description, _ = candidates[0]
        print(f"Automaticky vybrána ELATEC čtečka: {device}  {description}")
        return device
    if len(candidates) > 1:
        return _prompt_for_port(candidates, "Nalezeno více ELATEC čteček:")
    return _prompt_for_port(
        ports,
        "ELATEC čtečku se nepodařilo jednoznačně rozpoznat. Vyber port ručně:",
    )


def resolve_port(port: str | None, timeout: float) -> str:
    return select_port_interactively(timeout) if not port or port.lower() == "auto" else port
