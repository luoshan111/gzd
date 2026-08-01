"""日志、数据库备份和管理员用户管理 API。"""

import sqlite3
from datetime import datetime

from flask import request, send_file, session
from werkzeug.security import generate_password_hash

from app_common import admin_required, api_err, api_ok
from backup_utils import create_backup, get_backup_path, list_backups
from db import execute, query_all
from log_utils import db_log, read_logs, sys_log


def register_admin_routes(app):
    # ==================== 操作日志 API ====================

    @app.route('/api/logs')
    @admin_required
    def get_logs():
        """
        操作日志查询（仅管理员）。
        参数: category(system 系统日志 / db 数据库改动日志，默认 system)
              date(YYYY-MM-DD，默认今天) / level(INFO/WARNING/ERROR/DEBUG)
              / keyword / page / page_size(默认50，上限200)
        返回: logs（倒序，最新在前）+ total/pages/stats/dates（可用日期列表）
        """
        category = request.args.get('category', 'system').strip() or 'system'
        date = request.args.get('date', '').strip() or None
        level = request.args.get('level', '').strip().upper() or None
        keyword = request.args.get('keyword', '').strip() or None

        if category not in ('system', 'db'):
            return api_err('无效的日志类别，应为 system 或 db')
        if date:
            try:
                datetime.strptime(date, '%Y-%m-%d')
            except ValueError:
                return api_err('日期格式应为 YYYY-MM-DD')
        if level and level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            return api_err('无效的日志级别')

        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 50))
        except ValueError:
            return api_err('分页参数格式错误')

        return api_ok(**read_logs(category=category, date=date, level=level,
                                  keyword=keyword, page=page, page_size=page_size))


    # ==================== 管理员功能 API ====================

    @app.route('/api/admin/backup', methods=['POST'])
    @admin_required
    def create_backup_api():
        """手动创建数据库备份，并返回最新备份列表。"""
        try:
            backup_path = create_backup()
        except Exception:
            return api_err('数据库备份失败，请查看系统日志', status=500)

        db_log.info('管理员 %s 创建数据库备份: %s', session.get('username'), backup_path.name)
        return api_ok('数据库备份成功', filename=backup_path.name, backups=list_backups())


    @app.route('/api/admin/backups', methods=['GET'])
    @admin_required
    def get_backups():
        """获取数据库备份列表，仅返回文件名、大小和创建时间。"""
        return api_ok(data=list_backups())


    @app.route('/api/admin/backup/<path:filename>', methods=['GET'])
    @admin_required
    def download_backup(filename):
        """下载指定备份，文件名经过白名单校验以防止路径穿越。"""
        backup_path = get_backup_path(filename)
        if not backup_path:
            return api_err('备份文件不存在或不允许下载', status=404)
        sys_log.info('管理员 %s 下载数据库备份: %s', session.get('username'), filename)
        return send_file(backup_path, as_attachment=True, download_name=backup_path.name)


    @app.route('/api/admin/users', methods=['GET'])
    @admin_required
    def get_users():
        """获取所有登录用户列表。"""
        users = query_all(
            "SELECT id, username, is_admin, created_at FROM users ORDER BY id"
        )
        return api_ok(data=users)


    @app.route('/api/admin/user', methods=['POST'])
    @admin_required
    def create_user():
        """创建新用户。"""
        data = request.get_json(silent=True) or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        is_admin = 1 if data.get('is_admin') else 0

        if not username or not password:
            return api_err('用户名和密码不能为空')
        if len(password) < 4:
            return api_err('密码至少4位')

        try:
            execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), is_admin)
            )
        except sqlite3.IntegrityError:
            return api_err('用户名已存在', status=409)

        db_log.info('管理员 %s 创建用户 %s', session.get('username'), username)
        return api_ok('用户创建成功')


    @app.route('/api/admin/user/<int:user_id>', methods=['DELETE'])
    @admin_required
    def delete_user(user_id):
        """删除用户（不能删除自己的账户）。"""
        if user_id == session.get('user_id'):
            return api_err('不能删除自己的账户', status=409)

        deleted = execute("DELETE FROM users WHERE id = ?", (user_id,))
        if not deleted:
            return api_err('用户不存在', status=404)

        db_log.info('管理员 %s 删除用户 id=%s', session.get('username'), user_id)
        return api_ok('用户删除成功')


    @app.route('/api/admin/user/<int:user_id>/password', methods=['PUT'])
    @admin_required
    def reset_user_password(user_id):
        """重置指定用户的密码。"""
        data = request.get_json(silent=True) or {}
        password = data.get('password', '')

        if not password or len(password) < 4:
            return api_err('密码至少4位')

        updated = execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user_id)
        )
        if not updated:
            return api_err('用户不存在', status=404)

        db_log.info('管理员 %s 重置用户 id=%s 的密码', session.get('username'), user_id)
        return api_ok('密码重置成功')
