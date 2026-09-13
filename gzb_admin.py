"""
用户管理命令行工具
用于在后台管理用户账户，包括创建、删除、列出用户和重置密码

使用方法:
    python gzb_admin.py add <用户名> <密码> [--admin]  # 添加用户
    python gzb_admin.py del <用户名>                   # 删除用户
    python gzb_admin.py list                           # 列出所有用户
    python gzb_admin.py reset <用户名> <新密码>        # 重置密码
    python gzb_admin.py help                           # 显示帮助
"""

import sqlite3
import sys

from werkzeug.security import generate_password_hash

from db import init_db, now_local, query_all, execute


def create_user(username: str, password: str, is_admin: bool = False) -> None:
    """创建新用户，密码哈希后存储；用户名重复时给出提示。"""
    try:
        execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), 1 if is_admin else 0, now_local())
        )
        role = '(管理员)' if is_admin else '(普通用户)'
        print(f"用户 '{username}' 创建成功！{role}")
    except sqlite3.IntegrityError:
        print(f"错误：用户名 '{username}' 已存在")


def delete_user(username: str) -> None:
    """删除指定用户；用户不存在时给出提示。"""
    deleted = execute("DELETE FROM users WHERE username = ?", (username,))
    if deleted:
        print(f"用户 '{username}' 已删除")
    else:
        print(f"错误：用户 '{username}' 不存在")


def list_users() -> None:
    """以表格形式列出所有用户（ID、用户名、角色、创建时间）。"""
    users = query_all("SELECT id, username, is_admin, created_at FROM users ORDER BY id")

    if not users:
        print("暂无用户")
        return

    print("\n用户列表：")
    print("-" * 60)
    print(f"{'ID':<5} {'用户名':<15} {'角色':<10} {'创建时间':<20}")
    print("-" * 60)
    for user in users:
        role = "管理员" if user['is_admin'] else "普通用户"
        created = user['created_at'] or '-'
        print(f"{user['id']:<5} {user['username']:<15} {role:<10} {created:<20}")
    print("-" * 60)
    print(f"共 {len(users)} 个用户\n")


def reset_password(username: str, new_password: str) -> None:
    """重置指定用户的密码；用户不存在时给出提示。"""
    updated = execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (generate_password_hash(new_password), username)
    )
    if updated:
        print(f"用户 '{username}' 的密码已重置")
    else:
        print(f"错误：用户 '{username}' 不存在")


def show_help() -> None:
    """打印所有可用命令及使用示例。"""
    print("""
用户管理工具 - 使用说明
========================

命令：
  add <用户名> <密码> [--admin]   添加新用户（可选 --admin 设为管理员）
  del <用户名>                    删除用户
  list                            列出所有用户
  reset <用户名> <新密码>         重置用户密码
  help                            显示帮助信息

示例：
  python gzb_admin.py add zhangsan 123456
  python gzb_admin.py add lisi admin123 --admin
  python gzb_admin.py list
  python gzb_admin.py del zhangsan
  python gzb_admin.py reset lisi newpass123
""")


def main() -> None:
    """解析命令行参数并分发到对应功能。"""
    if len(sys.argv) < 2:
        show_help()
        return

    init_db()
    command = sys.argv[1].lower()

    if command == 'help':
        show_help()

    elif command == 'list':
        list_users()

    elif command == 'add':
        if len(sys.argv) < 4:
            print("用法: python gzb_admin.py add <用户名> <密码> [--admin]")
            return
        create_user(sys.argv[2], sys.argv[3], is_admin='--admin' in sys.argv)

    elif command == 'del':
        if len(sys.argv) < 3:
            print("用法: python gzb_admin.py del <用户名>")
            return
        delete_user(sys.argv[2])

    elif command == 'reset':
        if len(sys.argv) < 4:
            print("用法: python gzb_admin.py reset <用户名> <新密码>")
            return
        reset_password(sys.argv[2], sys.argv[3])

    else:
        print(f"未知命令: {command}")
        show_help()


if __name__ == '__main__':
    main()
