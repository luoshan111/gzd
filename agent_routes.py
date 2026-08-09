"""Agent 聊天 API 路由。"""

from flask import request, session
from app_common import api_err, api_ok, login_required
from agent_service import chat, clear_history


def register_agent_routes(app):

    @app.route('/api/chat', methods=['POST'])
    @login_required
    def chat_api():
        """处理用户的自然语言消息，返回 AI 助手回复。"""
        data = request.get_json(silent=True) or {}
        message = (data.get('message') or '').strip()
        if not message:
            return api_err('请输入消息')

        session_id = f"user_{session.get('user_id')}"

        try:
            reply = chat(session_id, message)
        except Exception as e:
            return api_err(f'AI 服务异常：{str(e)}', status=500)

        return api_ok(reply=reply)

    @app.route('/api/chat/clear', methods=['POST'])
    @login_required
    def clear_chat():
        """清除当前用户的对话历史。"""
        session_id = f"user_{session.get('user_id')}"
        clear_history(session_id)
        return api_ok('对话已重置')
