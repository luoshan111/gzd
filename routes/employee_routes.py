"""员工 HTTP 路由：只负责参数读取、权限和响应。"""

from flask import request, session

from core.app_common import admin_required, api_err, api_ok, login_required
from services.employee_service import (
    list_employees, list_recycle_bin, permanent_delete_employee,
    restore_employee, save_employee, search_employees, soft_delete_employee,
)


def _pagination_args(default_size=20):
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', default_size))
    except ValueError:
        return None
    return max(1, page), min(max(1, page_size), 100)


def register_employee_routes(app):
    @app.route('/api/search', methods=['GET'])
    @login_required
    def search():
        keyword = request.args.get('name', '').strip()
        if not keyword:
            return api_err('请输入查询关键词')
        results = search_employees(keyword)
        if not results:
            return api_err('未找到匹配的记录', status=404)
        return api_ok(data=results)

    @app.route('/api/employees', methods=['GET'])
    @login_required
    def get_employees():
        args = _pagination_args()
        if args is None:
            return api_err('分页参数格式错误')
        page, page_size = args
        keyword = request.args.get('q', '').strip()
        return api_ok(**list_employees(page, page_size, keyword))

    @app.route('/api/employee', methods=['POST', 'PUT'])
    @login_required
    def save_employee_api():
        message, error = save_employee(
            request.get_json(silent=True) or {}, session.get('username')
        )
        if error:
            return api_err(error)
        return api_ok(message)

    @app.route('/api/employee/<name>', methods=['DELETE'])
    @login_required
    def delete_employee_api(name):
        if not soft_delete_employee(name, session.get('username')):
            return api_err('未找到该员工，可能已被删除', status=404)
        return api_ok('删除成功，可在回收站中恢复')

    @app.route('/api/recycle-bin', methods=['GET'])
    @login_required
    def get_recycle_bin():
        args = _pagination_args()
        if args is None:
            return api_err('分页参数格式错误')
        page, page_size = args
        return api_ok(**list_recycle_bin(page, page_size))

    @app.route('/api/employee/<name>/restore', methods=['POST'])
    @login_required
    def restore_employee_api(name):
        if not restore_employee(name, session.get('username')):
            return api_err('回收站中未找到该员工', status=404)
        return api_ok('恢复成功')

    @app.route('/api/employee/<name>/permanent', methods=['DELETE'])
    @admin_required
    def permanent_delete_employee_api(name):
        if not permanent_delete_employee(name, session.get('username')):
            return api_err('回收站中未找到该员工', status=404)
        return api_ok('已彻底删除')
