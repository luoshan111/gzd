"""认证业务：登录、登出和密码修改。"""

from werkzeug.security import check_password_hash, generate_password_hash

from core.db import execute, query_one
from core.log_utils import db_log, sys_log


def authenticate(username: str, password: str):
    user = query_one(
        "SELECT id, username, password_hash, is_admin FROM users WHERE username = ?",
        (username,),
    )
    if not user or not check_password_hash(user['password_hash'], password):
        sys_log.info('用户 %s 登录失败', username)
        return None
    sys_log.info('用户 %s 登录成功', username)
    return user


def change_password(user_id: int, username: str, old_password: str, new_password: str):
    user = query_one("SELECT password_hash FROM users WHERE id = ?", (user_id,))
    if not user:
        return 'user_not_found'
    if not check_password_hash(user['password_hash'], old_password):
        return 'old_password_invalid'

    execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    db_log.info('用户 %s 修改了自己的密码', username)
    return 'ok'
