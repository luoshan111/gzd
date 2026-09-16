import json
import time
import logging
from openai import OpenAI
from agent_tools import get_tool_definitions, execute_tool
from config import AGENT_API_KEY, AGENT_BASE_URL, AGENT_MODEL

logger = logging.getLogger('agent')

# ── 配置（API key / 模型 / 接口地址统一定义在 config.py）────

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
- 导出时若对话中给出了某些人的考勤天数、每日工资或总工资，把这些数据逐人放进 payroll 参数（name/days/daily_wage/total_wage）；只提取用户明确说出的数字，不要编造或推算；没提到工资考勤就不要传 payroll。
- 总工资由系统填列：用户说了总工资就照填，此时每日工资留空、不要反推；没说总工资但天数和每日工资齐全时按"每日工资×考勤天数"计算。缺失的列会留空，可在回复中提醒用户补充。
- 查询结果较多时，只展示关键字段并提示总数。
- 如果用户意图不明确，主动询问。
- 如果用户要求的操作没有对应的可用工具，说明当前账号无权执行该操作，告知用户联系管理员，不要编造结果。"""

# ── 客户端管理 ──────────────────────────────────────────────

_client = None

def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=AGENT_API_KEY,
            base_url=AGENT_BASE_URL,
        )
    return _client

# ── 对话管理 ────────────────────────────────────────────────

# 按 session_id 存储对话历史（简单内存实现，生产环境建议用 Redis）
_conversations: dict = {}
_conversation_active: dict = {}  # session_id -> 最后活跃时间戳，用于过期清理

MAX_HISTORY = 20  # 保留最近 N 轮对话
CONVERSATION_TTL_SECONDS = 2 * 3600  # 会话闲置超过该时长后清理历史

def get_history(session_id: str) -> list:
    _conversation_active[session_id] = time.time()
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
    _conversation_active.pop(session_id, None)

def cleanup_conversations():
    """清理闲置超过 TTL 的会话历史，避免长期运行时内存持续增长。"""
    cutoff = time.time() - CONVERSATION_TTL_SECONDS
    expired = [sid for sid, last in _conversation_active.items() if last < cutoff]
    for sid in expired:
        _conversations.pop(sid, None)
        _conversation_active.pop(sid, None)

# ── 核心对话处理 ────────────────────────────────────────────

def chat(session_id: str, user_message: str, is_admin: bool = False) -> tuple:
    """
    处理一条用户消息，返回 (助手回复, 待下载文件列表)。
    支持多轮对话和工具调用；管理员专用工具仅对管理员会话开放。
    待下载文件列表形如 [{"token": ..., "filename": ...}]，供前端触发浏览器下载。
    """
    cleanup_conversations()
    client = get_client()
    history = get_history(session_id)

    # 添加用户消息
    add_message(session_id, "user", user_message)

    # 构建消息列表
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    tools = get_tool_definitions(is_admin=is_admin)

    try:
        response = client.chat.completions.create(
            model=AGENT_MODEL,
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
        return error_msg, []

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
        tool_results = []
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            logger.info("Agent 调用工具: %s(%s)", fn_name, fn_args)
            result = execute_tool(fn_name, fn_args, is_admin=is_admin)
            logger.info("工具返回: %s", result)
            tool_results.append(result)

            history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        # 工具生成的可下载文件（如导出 Excel）汇总给前端触发浏览器下载
        downloads = [
            {"token": r["download_token"], "filename": r["filename"]}
            for r in tool_results
            if isinstance(r, dict) and r.get("download_token")
        ]

        # 工具执行完毕，再次调用模型生成最终回复
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
        try:
            response2 = client.chat.completions.create(
                model=AGENT_MODEL,
                messages=messages,
                temperature=0.1,
                max_tokens=2000,
            )
            final_msg = response2.choices[0].message.content or "操作已完成。"
        except Exception as e:
            logger.exception("Agent 第二次调用失败")
            final_msg = "操作已完成，但生成回复时出错。"

        add_message(session_id, "assistant", final_msg)
        return final_msg, downloads

    # 无工具调用，直接返回文本
    reply = msg.content or "我不太理解您的意思，请重新描述一下。"
    add_message(session_id, "assistant", reply)
    return reply, []
