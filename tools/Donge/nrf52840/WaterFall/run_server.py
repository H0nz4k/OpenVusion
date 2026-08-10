import json
import os
from pathlib import Path

import uvicorn

BASE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("WATERFALL_CONFIG", os.environ.get("OPENVUSION_RF_CONFIG", BASE / "config.json")))

cfg = json.loads(CONFIG.read_text(encoding="utf-8"))

uvicorn.run(
    "app.main:app",
    host=str(cfg.get("host", "0.0.0.0")),
    port=int(cfg.get("port", 8088)),
    reload=False,
)
