"""Agent 聊天 API 路由。"""

import io

from flask import request, session, send_file
from app_common import api_err, api_ok, login_required
from agent_service import chat, clear_history
from agent_tools import get_download

# 与 Excel 导出接口保持一致的 MIME 类型
EXPORT_MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def register_agent_routes(app):

    @app.route('/api/chat', methods=['POST'])
    @login_required
    def chat_api():
        """处理用户的自然语言消息，返回 AI 助手回复和待下载文件列表。"""
        data = request.get_json(silent=True) or {}
        message = (data.get('message') or '').strip()
        if not message:
            return api_err('请输入消息')

        session_id = f"user_{session.get('user_id')}"
        is_admin = bool(session.get('is_admin'))

        try:
            reply, downloads = chat(session_id, message, is_admin=is_admin)
        except Exception as e:
            return api_err(f'AI 服务异常：{str(e)}', status=500)

        return api_ok(reply=reply, downloads=downloads)

    @app.route('/api/chat/download/<token>', methods=['GET'])
    @login_required
    def chat_download(token):
        """凭 token 领取 AI 助手生成的导出文件，直接作为附件下载。"""
        item = get_download(token)
        if item is None:
            return api_err('下载链接不存在或已过期，请重新让 AI 助手导出', status=404)
        return send_file(
            io.BytesIO(item['data']), as_attachment=True,
            download_name=item['filename'], mimetype=EXPORT_MIMETYPE,
        )

    @app.route('/api/chat/clear', methods=['POST'])
    @login_required
    def clear_chat():
        """清除当前用户的对话历史。"""
        session_id = f"user_{session.get('user_id')}"
        clear_history(session_id)
        return api_ok('对话已重置')
