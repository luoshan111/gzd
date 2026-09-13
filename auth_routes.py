"""登录、登出和登录状态相关路由。"""

from flask import jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app_common import api_err, api_ok, login_required
from db import execute, query_one
from log_utils import db_log, sys_log


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


    @app.route('/api/change-password', methods=['POST'])
    @login_required
    def api_change_password():
        """用户自助修改密码：验证旧密码后更新为新密码。"""
        data = request.get_json(silent=True) or {}
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')

        if not old_password or not new_password:
            return api_err('请输入旧密码和新密码')
        # 密码长度规则与管理员重置密码接口保持一致
        if len(new_password) < 4:
            return api_err('新密码至少4位')

        user = query_one(
            "SELECT password_hash FROM users WHERE id = ?",
            (session['user_id'],)
        )
        # 用户可能在登录期间被管理员删除，此时 session 仍有效，需单独提示
        if not user:
            return api_err('用户不存在', status=404)
        if not check_password_hash(user['password_hash'], old_password):
            return api_err('旧密码错误')

        execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), session['user_id'])
        )

        db_log.info('用户 %s 修改了自己的密码', session.get('username'))
        return api_ok('密码修改成功')


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
