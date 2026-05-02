import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import load_settings
from core.confirmation_commands import load_pending_action_records
import json

settings = load_settings()
records = load_pending_action_records(settings)
for k, v in records.items():
    print(f"{k}: {v.get('status')}")
