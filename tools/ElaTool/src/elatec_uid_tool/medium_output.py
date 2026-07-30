from .tagtypes import decode_supported_masks


def print_reader_info(info):
    print("\nČTEČKA")
    print("-" * 72)
    print(f"Port:              {info.port}")
    print(f"Verze:             {info.version or '(prázdná)'}")
    print(f"Device Type:       {info.device_type} (0x{info.device_type:02X})")
    print(f"LF supported mask: 0x{info.lf_supported_mask:08X}")
    print(f"HF supported mask: 0x{info.hf_supported_mask:08X}")
    print("\nPodporované technologie:")
    for item in decode_supported_masks(info.lf_supported_mask, info.hf_supported_mask):
        print(f"  0x{item.tag_type:02X}  {item.group:<4} {item.frequency:<11} {item.name}")


def print_medium_info(tag, tag_info):
    print("\nNALEZENÉ MÉDIUM")
    print("-" * 72)
    print(f"TagType:           0x{tag.tag_type:02X}")
    print(f"Definice:          {tag_info.definition}")
    print(f"Typ:               {tag_info.name}")
    print(f"Skupina:           {tag_info.group}")
    print(f"Frekvence:         {tag_info.frequency}")
    print(f"Počet bitů ID:     {tag.id_bit_count}")
    print(f"RAW UID:           {tag.id_hex}")
