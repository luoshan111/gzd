"""管理员业务：日志、备份和用户管理。"""

import sqlite3

from werkzeug.security import generate_password_hash

from core.backup_utils import create_backup, delete_backup, get_backup_path, list_backups
from core.db import execute, now_local, query_all
from core.log_utils import db_log, read_logs, sys_log


def query_operation_logs(category, date, level, keyword, page, page_size):
    return read_logs(
        category=category, date=date, level=level, keyword=keyword,
        page=page, page_size=page_size,
    )


def create_database_backup(username):
    path = create_backup()
    db_log.info('管理员 %s 创建数据库备份: %s', username, path.name)
    return path.name, list_backups()


def get_database_backups():
    return list_backups()


def get_downloadable_backup(filename, username):
    path = get_backup_path(filename)
    if path:
        sys_log.info('管理员 %s 下载数据库备份: %s', username, filename)
    return path


def remove_database_backup(filename, username):
    if not delete_backup(filename):
        return None
    db_log.info('管理员 %s 删除数据库备份: %s', username, filename)
    return list_backups()


def list_users():
    return query_all("SELECT id, username, is_admin, created_at FROM users ORDER BY id")


def create_user(username, password, is_admin, operator):
    try:
        execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) "
            "VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), is_admin, now_local()),
        )
    except sqlite3.IntegrityError:
        return False
    db_log.info('管理员 %s 创建用户 %s', operator, username)
    return True


def delete_user(user_id, operator_id, operator):
    if user_id == operator_id:
        return 'self'
    if not execute("DELETE FROM users WHERE id = ?", (user_id,)):
        return 'not_found'
    db_log.info('管理员 %s 删除用户 id=%s', operator, user_id)
    return 'ok'


def reset_user_password(user_id, password, operator):
    updated = execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), user_id),
    )
    if not updated:
        return False
    db_log.info('管理员 %s 重置用户 id=%s 的密码', operator, user_id)
    return True
