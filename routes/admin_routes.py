"""管理员 HTTP 路由：只负责参数读取、权限和响应。"""

from datetime import datetime

from flask import request, send_file, session

from core.app_common import admin_required, api_err, api_ok
from services.admin_service import (
    create_database_backup, create_user, delete_user, get_database_backups,
    get_downloadable_backup, list_users, query_operation_logs,
    remove_database_backup, reset_user_password,
)


def register_admin_routes(app):
    @app.route('/api/logs')
    @admin_required
    def get_logs():
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
        return api_ok(**query_operation_logs(
            category, date, level, keyword, page, page_size,
        ))

    @app.route('/api/admin/backup', methods=['POST'])
    @admin_required
    def create_backup_api():
        try:
            filename, backups = create_database_backup(session.get('username'))
        except Exception:
            return api_err('数据库备份失败，请查看系统日志', status=500)
        return api_ok('数据库备份成功', filename=filename, backups=backups)

    @app.route('/api/admin/backups', methods=['GET'])
    @admin_required
    def get_backups():
        return api_ok(data=get_database_backups())

    @app.route('/api/admin/backup/<path:filename>', methods=['GET'])
    @admin_required
    def download_backup(filename):
        path = get_downloadable_backup(filename, session.get('username'))
        if not path:
            return api_err('备份文件不存在或不允许下载', status=404)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.route('/api/admin/backup/<path:filename>', methods=['DELETE'])
    @admin_required
    def delete_backup_api(filename):
        backups = remove_database_backup(filename, session.get('username'))
        if backups is None:
            return api_err('备份文件不存在或不允许删除', status=404)
        return api_ok('备份删除成功', backups=backups)

    @app.route('/api/admin/users', methods=['GET'])
    @admin_required
    def get_users():
        return api_ok(data=list_users())

    @app.route('/api/admin/user', methods=['POST'])
    @admin_required
    def create_user_api():
        data = request.get_json(silent=True) or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        is_admin = 1 if data.get('is_admin') else 0
        if not username or not password:
            return api_err('用户名和密码不能为空')
        if len(password) < 4:
            return api_err('密码至少4位')
        if not create_user(username, password, is_admin, session.get('username')):
            return api_err('用户名已存在', status=409)
        return api_ok('用户创建成功')

    @app.route('/api/admin/user/<int:user_id>', methods=['DELETE'])
    @admin_required
    def delete_user_api(user_id):
        result = delete_user(user_id, session.get('user_id'), session.get('username'))
        if result == 'self':
            return api_err('不能删除自己的账户', status=409)
        if result == 'not_found':
            return api_err('用户不存在', status=404)
        return api_ok('用户删除成功')

    @app.route('/api/admin/user/<int:user_id>/password', methods=['PUT'])
    @admin_required
    def reset_user_password_api(user_id):
        data = request.get_json(silent=True) or {}
        password = data.get('password', '')
        if not password or len(password) < 4:
            return api_err('密码至少4位')
        if not reset_user_password(user_id, password, session.get('username')):
            return api_err('用户不存在', status=404)
        return api_ok('密码重置成功')
