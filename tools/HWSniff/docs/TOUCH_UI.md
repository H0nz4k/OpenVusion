# Touch UI

## Framework

**pygame-ce / pygame** — fullscreen, high-contrast buttons, no desktop chrome,
works with Linux framebuffer/SDL and touch via the input stack.

## Display

- Default layout: **480×320** landscape
- Auto-detect window/display size when available
- Config: `rotation` 0/90/180/270, `hide_cursor`, `fullscreen`
- No hard-coded framebuffer path

## State machine (minimum)

BOOTING → INITIALIZING → READER_SEARCH → READY | READER_MISSING  
READY → STARTING → WAITING_FOR_TAG → TAG_DETECTED → reading phases →  
VERIFYING → SAVING → SUCCESS | FAILURE → WAITING_FOR_REMOVAL → WAITING_FOR_TAG  
STOP → STOPPING → READY  
STORAGE_ERROR / FATAL_ERROR as terminal-ish gates

## Touch actions

| State | Actions |
|---|---|
| READY | START, optional SHUTDOWN |
| READER_MISSING | RETRY |
| WAITING_FOR_TAG / reading | STOP |
| SHUTDOWN confirm | ZRUŠIT / VYPNOUT |

No keyboard required. Technical tracebacks never shown on the main screen.
