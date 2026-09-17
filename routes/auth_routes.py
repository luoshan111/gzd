"""认证 HTTP 路由：只负责请求/响应适配。"""

from flask import redirect, render_template, request, session, url_for

from core.app_common import api_err, api_ok, login_required
from services.auth_service import authenticate, change_password
from core.log_utils import sys_log


def register_auth_routes(app):
    @app.route('/login')
    def login():
        if 'user_id' in session:
            return redirect(url_for('index'))
        return render_template('login.html')

    @app.route('/api/login', methods=['POST'])
    def api_login():
        data = request.get_json(silent=True) or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        if not username or not password:
            return api_err('请输入用户名和密码')
        user = authenticate(username, password)
        if not user:
            return api_err('用户名或密码错误', status=401)
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_admin'] = user['is_admin']
        return api_ok('登录成功', is_admin=user['is_admin'])

    @app.route('/api/logout', methods=['POST'])
    def api_logout():
        sys_log.info('用户 %s 退出登录', session.get('username'))
        session.clear()
        return api_ok('已退出登录')

    @app.route('/api/change-password', methods=['POST'])
    @login_required
    def api_change_password():
        data = request.get_json(silent=True) or {}
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')
        if not old_password or not new_password:
            return api_err('请输入旧密码和新密码')
        if len(new_password) < 4:
            return api_err('新密码至少4位')
        result = change_password(
            session['user_id'], session.get('username'), old_password, new_password,
        )
        if result == 'user_not_found':
            return api_err('用户不存在', status=404)
        if result == 'old_password_invalid':
            return api_err('旧密码错误')
        return api_ok('密码修改成功')

    @app.route('/api/check-login')
    def check_login():
        if 'user_id' not in session:
            return api_ok(logged_in=False)
        return api_ok(
            logged_in=True,
            username=session.get('username'),
            is_admin=session.get('is_admin', False),
        )
