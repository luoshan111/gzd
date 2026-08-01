"""登录、登出和登录状态相关路由。"""

from flask import jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from app_common import api_err, api_ok
from db import query_one
from log_utils import sys_log


def register_auth_routes(app):
    # ==================== 登录相关路由 ====================

    @app.route('/login')
    def login():
        """登录页面：已登录用户直接跳转主页。"""
        if 'user_id' in session:
            return redirect(url_for('index'))
        return render_template('login.html')


    @app.route('/api/login', methods=['POST'])
    def api_login():
        """登录接口：验证用户名密码，成功后写入 session。"""
        data = request.get_json(silent=True) or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return api_err('请输入用户名和密码')

        user = query_one(
            "SELECT id, username, password_hash, is_admin FROM users WHERE username = ?",
            (username,)
        )

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = user['is_admin']
            sys_log.info('用户 %s 登录成功', username)
            return api_ok('登录成功', is_admin=user['is_admin'])

        sys_log.info('用户 %s 登录失败', username)
        return api_err('用户名或密码错误', status=401)


    @app.route('/api/logout', methods=['POST'])
    def api_logout():
        """登出接口：清除 session。"""
        sys_log.info('用户 %s 退出登录', session.get('username'))
        session.clear()
        return api_ok('已退出登录')


    @app.route('/api/check-login')
    def check_login():
        """查询当前登录状态。"""
        if 'user_id' in session:
            return api_ok(
                logged_in=True,
                username=session.get('username'),
                is_admin=session.get('is_admin', False),
            )
        return api_ok(logged_in=False)
