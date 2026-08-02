"""员工信息和回收站相关 API。"""

from flask import request, session

from app_common import (
    EMPLOYEE_COLUMNS, RECYCLE_COLUMNS, admin_required, api_err, api_ok,
    get_employee_fields, login_required,
)
from db import execute, escape_like, get_pinyin_sx, query_all, query_one, query_paginated
from log_utils import db_log


def register_employee_routes(app):
    # ==================== 员工信息 API ====================

    @app.route('/api/search', methods=['GET'])
    @login_required
    def search():
        """
        按姓名或拼音首字母模糊搜索员工（不含已软删除记录）。
        关键词中的 %、_ 会被转义，按字面字符匹配，不会被当作通配符。
        """
        name = request.args.get('name', '').strip()
        if not name:
            return api_err('请输入查询关键词')

        keyword = f'%{escape_like(name)}%'
        results = query_all(
            f"SELECT {EMPLOYEE_COLUMNS} FROM employees "
            "WHERE deleted = 0 "
            "AND (real_name LIKE ? ESCAPE '\\' OR sx LIKE ? ESCAPE '\\') "
            "ORDER BY real_name",
            (keyword, keyword)
        )

        if results:
            return api_ok(data=results)
        return api_err('未找到匹配的记录', status=404)


    @app.route('/api/employees', methods=['GET'])
    @login_required
    def get_employees():
        """获取在职员工列表（分页，按姓名排序）。"""
        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 20))
        except ValueError:
            return api_err('分页参数格式错误')
        page = max(1, page)
        page_size = min(max(1, page_size), 100)

        result = query_paginated(
            f"SELECT {EMPLOYEE_COLUMNS} FROM employees WHERE deleted = 0 ORDER BY real_name",
            page=page, page_size=page_size
        )
        return api_ok(**result)


    @app.route('/api/employee', methods=['POST', 'PUT'])
    @login_required
    def save_employee():
        """
        保存员工信息（upsert 语义）：
        - 姓名不存在：新增
        - 姓名已存在且为正常记录：更新
        - 姓名已存在但已被软删除：恢复该记录并更新为新内容
        POST 与 PUT 行为一致。
        """
        data = request.get_json(silent=True) or {}
        fields = get_employee_fields(data)

        if not fields['real_name']:
            return api_err('姓名为必填项')

        fields['sx'] = get_pinyin_sx(fields['real_name'])
        params = (fields['id_number'], fields['bank_account'], fields['bank_address'],
                  fields['phone'], fields['sx'], fields['real_name'])

        existing = query_one(
            "SELECT deleted FROM employees WHERE real_name = ?", (fields['real_name'],)
        )

        if existing is None:
            execute('''
                INSERT INTO employees (real_name, id_number, bank_account, bank_address, phone, sx)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (fields['real_name'], fields['id_number'], fields['bank_account'],
                  fields['bank_address'], fields['phone'], fields['sx']))
            message = '信息添加成功'
            db_log.info('用户 %s 新增员工: %s', session.get('username'), fields['real_name'])
        elif existing['deleted']:
            execute('''
                UPDATE employees
                SET id_number=?, bank_account=?, bank_address=?, phone=?, sx=?,
                    deleted=0, deleted_at=NULL, deleted_by=NULL
                WHERE real_name=?
            ''', params)
            message = '信息添加成功（已恢复历史记录）'
            db_log.info('用户 %s 恢复已删除员工记录: %s', session.get('username'), fields['real_name'])
        else:
            execute('''
                UPDATE employees
                SET id_number=?, bank_account=?, bank_address=?, phone=?, sx=?
                WHERE real_name=?
            ''', params)
            message = '信息更新成功'
            db_log.info('用户 %s 更新员工: %s', session.get('username'), fields['real_name'])

        return api_ok(message)


    @app.route('/api/employee/<name>', methods=['DELETE'])
    @login_required
    def delete_employee(name):
        """
        按姓名删除员工（软删除：仅打标记并记录删除时间/操作人，数据保留便于审计）；
        姓名不存在或已删除时返回明确提示。
        """
        deleted = execute(
            "UPDATE employees SET deleted = 1, deleted_at = CURRENT_TIMESTAMP, deleted_by = ? "
            "WHERE real_name = ? AND deleted = 0",
            (session.get('username'), name)
        )
        if deleted:
            db_log.info('用户 %s 删除员工: %s', session.get('username'), name)
            return api_ok('删除成功，可在回收站中恢复')
        return api_err('未找到该员工，可能已被删除', status=404)


    # ==================== 回收站 API ====================

    @app.route('/api/recycle-bin', methods=['GET'])
    @login_required
    def get_recycle_bin():
        """获取回收站列表（分页）：已软删除的员工，按删除时间倒序。"""
        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 20))
        except ValueError:
            return api_err('分页参数格式错误')
        page = max(1, page)
        page_size = min(max(1, page_size), 100)

        result = query_paginated(
            f"SELECT {RECYCLE_COLUMNS} FROM employees WHERE deleted = 1 ORDER BY deleted_at DESC",
            page=page, page_size=page_size
        )
        return api_ok(**result)


    @app.route('/api/employee/<name>/restore', methods=['POST'])
    @login_required
    def restore_employee(name):
        """从回收站恢复员工记录（清除删除标记与审计信息）。"""
        restored = execute(
            "UPDATE employees SET deleted = 0, deleted_at = NULL, deleted_by = NULL "
            "WHERE real_name = ? AND deleted = 1",
            (name,)
        )
        if restored:
            db_log.info('用户 %s 从回收站恢复员工: %s', session.get('username'), name)
            return api_ok('恢复成功')
        return api_err('回收站中未找到该员工', status=404)


    @app.route('/api/employee/<name>/permanent', methods=['DELETE'])
    @admin_required
    def permanent_delete_employee(name):
        """
        彻底删除员工记录（物理删除，不可恢复）。
        仅管理员可操作，且只能删除已在回收站中的记录（防止绕过软删除直接物理删除）。
        """
        deleted = execute(
            "DELETE FROM employees WHERE real_name = ? AND deleted = 1",
            (name,)
        )
        if deleted:
            db_log.warning('管理员 %s 彻底删除员工: %s', session.get('username'), name)
            return api_ok('已彻底删除')
        return api_err('回收站中未找到该员工', status=404)
