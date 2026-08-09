import os
import json
import logging
from openai import OpenAI
from agent_tools import get_tool_definitions, execute_tool

logger = logging.getLogger('agent')

# ── 配置 ────────────────────────────────────────────────────

DEFAULT_MODEL = os.environ.get("GZD_AGENT_MODEL", "gpt-4o-mini")
DEFAULT_BASE_URL = os.environ.get("GZD_AGENT_BASE_URL", None)
DEFAULT_API_KEY = os.environ.get("GZD_AGENT_API_KEY") or os.environ.get("OPENAI_API_KEY", "")

SYSTEM_PROMPT = """你是员工信息管理系统的 AI 助手。你可以帮助用户完成以下操作：

1. 查询/搜索员工信息
2. 新增、更新、删除员工
3. 恢复回收站中的员工
4. 批量导出员工信息到 Excel
5. 批量更新员工信息
6. 创建数据库备份
7. 查看系统操作日志
8. 统计员工数量

规则：
- 用简洁的中文回复。
- 涉及删除操作时，先确认用户意图。
- 当用户提供了一批数据（如多个姓名、多条员工信息），尽量一次调用批量工具完成。
- 查询结果较多时，只展示关键字段并提示总数。
- 如果用户意图不明确，主动询问。"""

# ── 客户端管理 ──────────────────────────────────────────────

_client = None

def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=DEFAULT_API_KEY,
            base_url=DEFAULT_BASE_URL,
        )
    return _client

# ── 对话管理 ────────────────────────────────────────────────

# 按 session_id 存储对话历史（简单内存实现，生产环境建议用 Redis）
_conversations: dict = {}

MAX_HISTORY = 20  # 保留最近 N 轮对话

def get_history(session_id: str) -> list:
    if session_id not in _conversations:
        _conversations[session_id] = []
    return _conversations[session_id]

def add_message(session_id: str, role: str, content: str):
    history = get_history(session_id)
    history.append({"role": role, "content": content})
    # 保留最近对话
    if len(history) > MAX_HISTORY * 2:
        _conversations[session_id] = history[-(MAX_HISTORY * 2):]

def clear_history(session_id: str):
    _conversations.pop(session_id, None)

# ── 核心对话处理 ────────────────────────────────────────────

def chat(session_id: str, user_message: str) -> str:
    """
    处理一条用户消息，返回助手回复。
    支持多轮对话和工具调用。
    """
    client = get_client()
    history = get_history(session_id)

    # 添加用户消息
    add_message(session_id, "user", user_message)

    # 构建消息列表
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    tools = get_tool_definitions()

    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=2000,
        )
    except Exception as e:
        logger.exception("Agent API 调用失败")
        error_msg = f"AI 服务调用失败：{str(e)}"
        add_message(session_id, "assistant", error_msg)
        return error_msg

    msg = response.choices[0].message

    # 处理工具调用
    if msg.tool_calls:
        # 将助手消息加入历史
        history.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in msg.tool_calls
            ]
        })

        # 执行每个工具调用
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            logger.info("Agent 调用工具: %s(%s)", fn_name, fn_args)
            result = execute_tool(fn_name, fn_args)
            logger.info("工具返回: %s", result)

            history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        # 工具执行完毕，再次调用模型生成最终回复
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
        try:
            response2 = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=messages,
                temperature=0.1,
                max_tokens=2000,
            )
            final_msg = response2.choices[0].message.content or "操作已完成。"
        except Exception as e:
            logger.exception("Agent 第二次调用失败")
            final_msg = "操作已完成，但生成回复时出错。"

        add_message(session_id, "assistant", final_msg)
        return final_msg

    # 无工具调用，直接返回文本
    reply = msg.content or "我不太理解您的意思，请重新描述一下。"
    add_message(session_id, "assistant", reply)
    return reply
