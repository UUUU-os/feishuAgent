import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import load_settings
from adapters import FeishuClient
from core import extract_text_from_message

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

for msg in messages[-20:]: # Last 20
    print(f"ID: {msg.get('message_id')}")
    print(f"Text: {extract_text_from_message(msg)}")
    print("---")
