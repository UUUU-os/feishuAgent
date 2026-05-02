import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import load_settings
from adapters import FeishuClient
import json

settings = load_settings()
client = FeishuClient(settings.feishu)
chat_id = settings.feishu.default_chat_id
data = client.list_chat_messages(chat_id=chat_id, identity="user", page_size=50)
for msg in data.get("items", []):
    content = msg.get("body", {}).get("content", "")
    if "拒绝" in content:
        print(json.dumps(msg, ensure_ascii=False, indent=2))
        print("---")
