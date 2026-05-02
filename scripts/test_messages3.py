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
messages = []
while data.get("items"):
    messages.extend(data.get("items"))
    if not data.get("has_more"):
        break
    data = client.list_chat_messages(chat_id=chat_id, identity="user", page_size=50, page_token=data.get("page_token"))

for msg in messages:
    if msg.get('message_id') == 'om_x100b50722167eca0b4860167356b1ef':
        print(json.dumps(msg, ensure_ascii=False, indent=2))
