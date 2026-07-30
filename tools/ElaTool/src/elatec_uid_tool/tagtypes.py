from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagTypeInfo:
    tag_type: int
    definition: str
    name: str
    group: str
    frequency: str


LF_NAMES: dict[int, tuple[str, str, str]] = {
    0x40: ("LFTAG_EM4102", "EM4102 / CASI-RUSCO / EM4x02", "125 kHz"),
    0x41: ("LFTAG_HITAG1S", "HITAG 1 / HITAG S", "125 kHz"),
    0x42: ("LFTAG_HITAG2", "HITAG 2", "125 kHz"),
    0x43: ("LFTAG_EM4150", "EM4150 / EM4x50", "125 kHz"),
    0x44: ("LFTAG_AT5555", "AT5555 / AT5557 / AT5577 / Q5", "125 kHz"),
    0x45: ("LFTAG_ISOFDX", "ISO FDX-B / EM4105", "134.2 kHz"),
    0x46: ("LFTAG_EM4026", "EM4026", "125 kHz"),
    0x47: ("LFTAG_HITAGU", "HITAG µ", "125 kHz"),
    0x48: ("LFTAG_EM4305", "EM4305", "125 kHz"),
    0x49: ("LFTAG_HIDPROX", "HID Prox", "125 kHz"),
    0x4A: ("LFTAG_TIRIS", "ISO HDX / TIRIS", "134.2 kHz"),
    0x4B: ("LFTAG_COTAG", "Cotag", "134.2 kHz"),
    0x4C: ("LFTAG_IOPROX", "ioProx", "125 kHz"),
    0x4D: ("LFTAG_INDITAG", "Indala", "125 kHz"),
    0x4E: ("LFTAG_HONEYTAG", "NexWatch", "125 kHz"),
    0x4F: ("LFTAG_AWID", "AWID", "125 kHz"),
    0x50: ("LFTAG_GPROX", "G-Prox", "125 kHz"),
    0x51: ("LFTAG_PYRAMID", "Pyramid", "125 kHz"),
    0x52: ("LFTAG_KERI", "Keri", "125 kHz"),
    0x53: ("LFTAG_DEISTER", "Deister", "125 kHz"),
    0x54: ("LFTAG_CARDAX", "Cardax", "125 kHz"),
    0x55: ("LFTAG_NEDAP", "Nedap", "125 kHz"),
    0x56: ("LFTAG_PAC", "PAC", "134.2 kHz"),
    0x57: ("LFTAG_IDTECK", "IDTECK", "125 kHz"),
    0x58: ("LFTAG_ULTRAPROX", "UltraProx", "125 kHz"),
    0x59: ("LFTAG_ICT", "ICT", "125 kHz"),
    0x5A: ("LFTAG_ISONAS", "Isonas", "125 kHz"),
}

HF_NAMES: dict[int, tuple[str, str, str]] = {
    0x80: ("HFTAG_MIFARE", "ISO14443A / MIFARE", "13.56 MHz"),
    0x81: ("HFTAG_ISO14443B", "ISO14443B", "13.56 MHz"),
    0x82: ("HFTAG_ISO15693", "ISO15693", "13.56 MHz"),
    0x83: ("HFTAG_LEGIC", "LEGIC", "13.56 MHz"),
    0x84: ("HFTAG_HIDICLASS", "HID iCLASS", "13.56 MHz"),
    0x85: ("HFTAG_FELICA", "FeliCa", "13.56 MHz"),
    0x86: ("HFTAG_SRX", "SRX", "13.56 MHz"),
    0x87: ("HFTAG_NFCP2P", "NFC Peer-to-Peer", "13.56 MHz"),
    0x88: ("HFTAG_BLE", "Bluetooth Low Energy credential", "2.4 GHz"),
    0x89: ("HFTAG_TOPAZ", "Topaz / NFC Type 1", "13.56 MHz"),
    0x8A: ("HFTAG_CTS", "CTS", "13.56 MHz"),
    0x8B: ("HFTAG_BLELC", "Bluetooth Low Energy LC", "2.4 GHz"),
}


def get_tag_type_info(tag_type: int) -> TagTypeInfo:
    if tag_type in LF_NAMES:
        definition, name, frequency = LF_NAMES[tag_type]
        return TagTypeInfo(tag_type, definition, name, "LF", frequency)
    if tag_type in HF_NAMES:
        definition, name, frequency = HF_NAMES[tag_type]
        group = "BLE" if tag_type in (0x88, 0x8B) else "HF"
        return TagTypeInfo(tag_type, definition, name, group, frequency)
    return TagTypeInfo(
        tag_type=tag_type,
        definition=f"TAGTYPE_0x{tag_type:02X}",
        name="Neznámý nebo novější typ",
        group="UNKNOWN",
        frequency="neznámá",
    )


def mask_contains(mask: int, tag_type: int) -> bool:
    return bool(mask & (1 << (tag_type & 0x1F)))


def decode_supported_masks(lf_mask: int, hf_mask: int) -> list[TagTypeInfo]:
    result: list[TagTypeInfo] = []
    for tag_type in sorted(LF_NAMES):
        if mask_contains(lf_mask, tag_type):
            result.append(get_tag_type_info(tag_type))
    for tag_type in sorted(HF_NAMES):
        if mask_contains(hf_mask, tag_type):
            result.append(get_tag_type_info(tag_type))
    return result
