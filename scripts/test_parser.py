import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import load_settings
from core.confirmation_commands import extract_text_from_message
from scripts.post_meeting_confirmation_watcher import build_reply_confirmation_command

settings = load_settings()
msg = {
  "body": {
    "content": "{\"text\":\"@_user_1 拒绝\"}"
  },
  "chat_id": "oc_3e432398cc43063fda2b2d322bb6dead",
  "create_time": "1777624826765",
  "deleted": False,
  "mentions": [
    {
      "id": "ou_7f395b60b857c97e2c36f66712aba5cd",
      "id_type": "open_id",
      "key": "@_user_1",
      "name": "飞书Agent",
      "tenant_key": "1abd20e084069b82"
    }
  ],
  "message_id": "om_x100b50722167eca0b4860167356b1ef",
  "message_position": "62",
  "msg_type": "text",
  "parent_id": "om_x100b5071228a14acb4afc54f28b69ae",
  "root_id": "om_x100b5071228a14acb4afc54f28b69ae",
  "sender": {
    "id": "ou_709153a65286899de8e61adcf8d52850",
    "id_type": "open_id",
    "sender_type": "user",
    "tenant_key": "1abd20e084069b82"
  },
  "update_time": "1777624826859",
  "updated": True
}

text = extract_text_from_message(msg)
print(f"text: {text}")
cmd = build_reply_confirmation_command(settings, msg, text)
print(f"command: {cmd}")
