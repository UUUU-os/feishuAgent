# M3 会前知识卡片真实联调报告

## 1. 会议输入

- event_id: `af0e57dd-a93a-458d-b484-e9a57f7a3bed_0`
- 标题: MeetFlow 测试会议
- 开始时间: `2026-05-05`
- 结束时间: `2026-05-06`
- 参会人数: `0`
- allow_write: `True`

## 2. 工作流阶段

```text
真实日历会议 -> 真实文档读取 -> 文档清洗与 chunk -> 向量/BM25 索引 -> meeting.soon -> PreMeetingBriefWorkflow -> knowledge.search -> im.send_card(allow_write 时)
```

## 3. 检索 Query

```json
{
  "meeting_id": "af0e57dd-a93a-458d-b484-e9a57f7a3bed_0",
  "calendar_event_id": "af0e57dd-a93a-458d-b484-e9a57f7a3bed_0",
  "project_id": "meetflow",
  "meeting_title": "MeetFlow 测试会议",
  "meeting_description": "",
  "entities": [
    "MeetFlow",
    "测试会议"
  ],
  "attendee_names": [],
  "attachment_titles": [],
  "related_resource_titles": [],
  "resource_types": [
    "doc",
    "sheet",
    "minute",
    "task"
  ],
  "time_window": "recent_90_days",
  "search_queries": [
    "meetflow / 测试会议",
    "MeetFlow 测试会议",
    "meetflow",
    "MeetFlow",
    "测试会议"
  ],
  "confidence": 0.7,
  "missing_context": [
    "participants",
    "related_resources"
  ],
  "extra": {
    "identified_topic": "meetflow / 测试会议",
    "topic_signal": {
      "topic": "meetflow / 测试会议",
      "candidate_projects": [
        {
          "project_id": "meetflow",
          "name": "meetflow",
          "score": 0.7,
          "matched_signals": [
            "meetflow",
            "project_id:meetflow"
          ],
          "source": "memory"
        }
      ],
      "business_entities": [
        "MeetFlow",
        "测试会议"
      ],
      "attendee_signals": [],
      "confidence": 0.7,
      "missing_context": [
        "participants"
      ],
      "query_hints": [
        "meetflow / 测试会议",
        "meetflow",
        "MeetFlow",
        "测试会议"
      ],
      "needs_confirmation": true,
      "reason": "候选项目 meetflow 命中 meetflow, project_id:meetflow；识别到实体 MeetFlow, 测试会议；缺少上下文 participants"
    },
    "start_time": "2026-05-05",
    "end_time": "2026-05-06",
    "timezone": "",
    "organizer": ""
  }
}
```

## 4. 索引资源与 Chunk

## 5. 工具检索结果

### knowledge.search `success`

```json
{
  "query": "MeetFlow 测试会议",
  "hits": [],
  "omitted_count": 0,
  "token_budget": 600,
  "used_tokens": 0,
  "knowledge_namespace": "sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce",
  "vector_collection_name": "meetflow_knowledge_chunks_137933ce",
  "embedding_provider": "sentence-transformers",
  "embedding_model": "BAAI/bge-small-zh-v1.5",
  "embedding_dimensions": 512,
  "low_confidence": true,
  "reason": "混合检索未召回到满足阈值的知识片段，请确认资源是否已索引或放宽查询条件；namespace=sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce collection=meetflow_knowledge_chunks_137933ce。"
}
```

### im.send_card `success`

```json
{
  "body": {
    "content": "{\"title\":\"MeetFlow 会前背景卡：MeetFlow 测试会议\",\"elements\":[[{\"tag\":\"text\",\"text\":\"主题\"},{\"tag\":\"text\",\"text\":\"：MeetFlow 测试会议\\n\"},{\"tag\":\"text\",\"text\":\"状态\"},{\"tag\":\"text\",\"text\":\"：可参考  |  \"},{\"tag\":\"text\",\"text\":\"置信度\"},{\"tag\":\"text\",\"text\":\"：0.80\\n\"},{\"tag\":\"text\",\"text\":\"背景摘要\"},{\"tag\":\"text\",\"text\":\"：scripted_debug 已完成真实会议读取、知识检索和受控发卡。\"}],[{\"tag\":\"hr\"}],[{\"tag\":\"hr\"}],[{\"tag\":\"button\",\"text\":\"刷新背景\",\"type\":\"primary\"},{\"tag\":\"button\",\"text\":\"生成待办草案\",\"type\":\"default\"},{\"tag\":\"button\",\"text\":\"发给我\",\"type\":\"default\"}]]}"
  },
  "chat_id": "oc_d3e31969e4b527ee929db9cfb1493bb6",
  "create_time": "1777964677827",
  "deleted": false,
  "message_id": "om_x100b50ad269420a0b106a93737968f7",
  "msg_type": "interactive",
  "sender": {
    "id": "cli_a97994d9e1f81cc3",
    "id_type": "app_id",
    "sender_type": "app",
    "tenant_key": "1abd20e084069b82"
  },
  "update_time": "1777964677827",
  "updated": false,
  "card_delivery": "full_card"
}
```

## 6. 卡片 Payload 草案

```json
{
  "title": "MeetFlow 会前背景卡：meetflow / 测试会议",
  "summary": "meetflow / 测试会议 的上下文证据不足，当前只召回到可能相关资料，建议人工确认后再推送。",
  "facts": [
    {
      "label": "会议主题",
      "value": "meetflow / 测试会议"
    },
    {
      "label": "背景摘要",
      "value": "meetflow / 测试会议 的上下文证据不足，当前只召回到可能相关资料，建议人工确认后再推送。"
    },
    {
      "label": "置信度",
      "value": "0.70"
    },
    {
      "label": "状态",
      "value": "上下文不足，建议人工确认后再推送"
    }
  ],
  "sections": [
    {
      "key": "last_decisions",
      "title": "上次结论",
      "empty": "暂无明确结论",
      "items": []
    },
    {
      "key": "current_questions",
      "title": "当前问题",
      "empty": "暂无待确认问题",
      "items": []
    },
    {
      "key": "risks",
      "title": "风险点",
      "empty": "暂无显著风险",
      "items": []
    },
    {
      "key": "must_read_resources",
      "title": "待读资料",
      "empty": "暂无必读资料",
      "items": []
    },
    {
      "key": "possible_related_resources",
      "title": "可能相关资料",
      "empty": "暂无候选资料",
      "items": []
    }
  ],
  "card": {
    "config": {
      "wide_screen_mode": true
    },
    "header": {
      "template": "orange",
      "title": {
        "tag": "plain_text",
        "content": "MeetFlow 会前背景卡：meetflow / 测试会议"
      }
    },
    "elements": [
      {
        "tag": "markdown",
        "content": "**主题**：meetflow / 测试会议\n**状态**：需确认  |  **置信度**：0.70\n**背景摘要**：meetflow / 测试会议 的上下文证据不足，当前只召回到可能相关资料，建议人工确认后再推送。"
      },
      {
        "tag": "hr"
      },
      {
        "tag": "hr"
      },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "button",
            "text": {
              "tag": "plain_text",
              "content": "刷新背景"
            },
            "type": "primary",
            "value": {
              "action": "refresh_pre_meeting_brief",
              "workflow_type": "pre_meeting_brief",
              "meeting_id": "af0e57dd-a93a-458d-b484-e9a57f7a3bed_0",
              "calendar_event_id": "af0e57dd-a93a-458d-b484-e9a57f7a3bed_0",
              "source_card": "pre_meeting_brief"
            }
          },
          {
            "tag": "button",
            "text": {
              "tag": "plain_text",
              "content": "生成待办草案"
            },
            "type": "default",
            "value": {
              "action": "create_task_draft",
              "workflow_type": "pre_meeting_brief",
              "meeting_id": "af0e57dd-a93a-458d-b484-e9a57f7a3bed_0",
              "calendar_event_id": "af0e57dd-a93a-458d-b484-e9a57f7a3bed_0",
              "source_card": "pre_meeting_brief"
            }
          },
          {
            "tag": "button",
            "text": {
              "tag": "plain_text",
              "content": "发给我"
            },
            "type": "default",
            "value": {
              "action": "send_summary_to_me",
              "workflow_type": "pre_meeting_brief",
              "meeting_id": "af0e57dd-a93a-458d-b484-e9a57f7a3bed_0",
              "calendar_event_id": "af0e57dd-a93a-458d-b484-e9a57f7a3bed_0",
              "source_card": "pre_meeting_brief"
            }
          }
        ]
      }
    ]
  },
  "source_meeting_id": "af0e57dd-a93a-458d-b484-e9a57f7a3bed_0",
  "idempotency_key": "pre_meeting_brief:af0e57dd-a93a-458d-b484-e9a57f7a3bed_0"
}
```

## 7. Agent 最终结果

- status: `success`
- trace_id: `b3cecc9e1f6a`

```text
scripted_debug 最终回复：工具 im.send_card 执行成功。
结构化数据 JSON：
{
  "body": {
    "content": "{\"title\":\"MeetFlow 会前背景卡：MeetFlow 测试会议\",\"elements\":[[{\"tag\":\"text\",\"text\":\"主题\"},{\"tag\":\"text\",\"text\":\"：MeetFlow 测试会议\\n\"},{\"tag\":\"text\",\"text\":\"状态\"},{\"tag\":\"text\",\"text\":\"：可参考  |  \"},{\"tag\":\"text\",\"text\":\"置信度\"},{\"tag\":\"text\",\"text\":\"：0.80\\n\"},{\"tag\":\"text\",\"text\":\"背景摘要\"},{\"tag\":\"text\",\"text\":\"：scripted_debug 已完成真实会议读取、知识检索和受控发卡。\"}],[{\"tag\":\"hr\"}],[{\"tag\":\"hr\"}],[{\"tag\":\"button\",\"text\":\"刷新背景\",\"type\":\"primary\"},{\"tag\":\"button\",\"text\":\"生成待办草案\",\"type\":\"default\"},{\"tag\":\"button\",\"text\":\"发给我\",\"type\":\"default\"}]]}"
  },
  "chat_id": "oc_d3e31969e4b527ee929db9cfb1493bb6",
  "create_time": "1777964677827",
  "deleted": false,
  "message_id": "om_x100b50ad269420a0b106a93737968f7",
  "msg_type": "interactive",
  "sender": {
    "id": "cli_a97994d9e1f81cc3",
    "id_type": "app_id",
    "sender_type": "app",
    "tenant_key": "1abd20e084069b82"
  },
  "update_time": "1777964677827",
  "updated": false,
  "card_delivery": "full_card"
}
```
