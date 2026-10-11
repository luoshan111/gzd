"""员工资料和回收站业务。"""

from core.app_common import EMPLOYEE_COLUMNS, RECYCLE_COLUMNS, get_employee_fields
from core.db import (
    execute, escape_like, get_pinyin_sx, now_local, query_all, query_one,
    query_paginated,
)
from core.log_utils import db_log


def search_employees(keyword: str):
    escaped = f'%{escape_like(keyword)}%'
    return query_all(
        f"SELECT {EMPLOYEE_COLUMNS} FROM employees "
        "WHERE deleted = 0 "
        "AND (real_name LIKE ? ESCAPE '\\' OR sx LIKE ? ESCAPE '\\') "
        "ORDER BY real_name",
        (escaped, escaped),
    )


def list_employees(page: int, page_size: int, keyword: str = ''):
    where = 'WHERE deleted = 0'
    params = ()
    if keyword:
        where += " AND (real_name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\' OR sx LIKE ? ESCAPE '\\')"
        escaped = f'%{escape_like(keyword)}%'
        params = (escaped, escaped, escaped)
    return query_paginated(
        f"SELECT {EMPLOYEE_COLUMNS} FROM employees {where} ORDER BY real_name",
        params=params, page=page, page_size=page_size,
    )


def save_employee(data: dict, username: str):
    fields = get_employee_fields(data)
    if not fields['real_name']:
        return None, '姓名为必填项'

    fields['sx'] = get_pinyin_sx(fields['real_name'])
    params = (
        fields['id_number'], fields['bank_account'], fields['bank_address'],
        fields['phone'], fields['sx'], fields['real_name'],
    )
    existing = query_one(
        "SELECT deleted FROM employees WHERE real_name = ?", (fields['real_name'],)
    )

    if existing is None:
        execute(
            'INSERT INTO employees '
            '(real_name, id_number, bank_account, bank_address, phone, sx) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (fields['real_name'], fields['id_number'], fields['bank_account'],
             fields['bank_address'], fields['phone'], fields['sx']),
        )
        db_log.info('用户 %s 新增员工: %s', username, fields['real_name'])
        return '信息添加成功', None

    if existing['deleted']:
        execute(
            'UPDATE employees SET id_number=?, bank_account=?, bank_address=?, '
            'phone=?, sx=?, deleted=0, deleted_at=NULL, deleted_by=NULL '
            'WHERE real_name=?', params,
        )
        db_log.info('用户 %s 恢复已删除员工记录: %s', username, fields['real_name'])
        return '信息添加成功（已恢复历史记录）', None

    execute(
        'UPDATE employees SET id_number=?, bank_account=?, bank_address=?, '
        'phone=?, sx=? WHERE real_name=?', params,
    )
    db_log.info('用户 %s 更新员工: %s', username, fields['real_name'])
    return '信息更新成功', None


def soft_delete_employee(name: str, username: str):
    changed = execute(
        "UPDATE employees SET deleted = 1, deleted_at = ?, deleted_by = ? "
        "WHERE real_name = ? AND deleted = 0",
        (now_local(), username, name),
    )
    if not changed:
        return False
    db_log.info('用户 %s 删除员工: %s', username, name)
    return True


def list_recycle_bin(page: int, page_size: int):
    return query_paginated(
        f"SELECT {RECYCLE_COLUMNS} FROM employees WHERE deleted = 1 ORDER BY deleted_at DESC",
        page=page, page_size=page_size,
    )


def restore_employee(name: str, username: str):
    changed = execute(
        "UPDATE employees SET deleted = 0, deleted_at = NULL, deleted_by = NULL "
        "WHERE real_name = ? AND deleted = 1", (name,),
    )
    if not changed:
        return False
    db_log.info('用户 %s 从回收站恢复员工: %s', username, name)
    return True


def permanent_delete_employee(name: str, username: str):
    changed = execute(
        "DELETE FROM employees WHERE real_name = ? AND deleted = 1", (name,)
    )
    if not changed:
        return False
    db_log.warning('管理员 %s 彻底删除员工: %s', username, name)
    return True
