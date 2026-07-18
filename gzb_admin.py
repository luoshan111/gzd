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

# 数据库文件路径
DB_PATH = 'sjk.db'


def get_db_connection():
    """
    获取数据库连接
    返回: sqlite3.Connection对象，设置了row_factory以便通过列名访问结果
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_user(username, password, is_admin=False):
    """
    创建新用户
    
    参数:
        username: 用户名
        password: 明文密码
        is_admin: 是否为管理员，默认为False
    
    功能:
        将用户信息插入数据库，密码经过哈希处理后存储
        如果用户名已存在，则提示错误
    """
    conn = get_db_connection()
    # 对密码进行哈希处理，安全存储
    password_hash = generate_password_hash(password)
    
    try:
        # 插入新用户记录
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username, password_hash, 1 if is_admin else 0)
        )
        conn.commit()
        print(f"用户 '{username}' 创建成功！{'(管理员)' if is_admin else '(普通用户)'}")
    except sqlite3.IntegrityError:
        # 用户名已存在（违反UNIQUE约束）
        print(f"错误：用户名 '{username}' 已存在")
    finally:
        conn.close()


def delete_user(username):
    """
    删除用户
    
    参数:
        username: 要删除的用户名
    
    功能:
        从数据库中删除指定用户
        如果用户不存在，则提示错误
    """
    conn = get_db_connection()
    # 执行删除操作
    cursor = conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    
    # 检查是否成功删除（rowcount > 0 表示有记录被删除）
    if cursor.rowcount > 0:
        print(f"用户 '{username}' 已删除")
    else:
        print(f"错误：用户 '{username}' 不存在")
    conn.close()


def list_users():
    """
    列出所有用户
    
    功能:
        从数据库查询所有用户，并以表格形式打印出来
        显示信息包括：ID、用户名、角色（管理员/普通用户）、创建时间
    """
    conn = get_db_connection()
    # 查询所有用户，按ID排序
    users = conn.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()
    conn.close()
    
    if not users:
        print("暂无用户")
        return
    
    # 打印用户列表表格
    print("\n用户列表：")
    print("-" * 60)
    print(f"{'ID':<5} {'用户名':<15} {'角色':<10} {'创建时间':<20}")
    print("-" * 60)
    
    for user in users:
        # 根据is_admin字段判断角色
        role = "管理员" if user['is_admin'] else "普通用户"
        created = user['created_at'] or '-'
        print(f"{user['id']:<5} {user['username']:<15} {role:<10} {created:<20}")
    
    print("-" * 60)
    print(f"共 {len(users)} 个用户\n")


def reset_password(username, new_password):
    """
    重置用户密码
    
    参数:
        username: 用户名
        new_password: 新的明文密码
    
    功能:
        更新指定用户的密码，新密码经过哈希处理后存储
        如果用户不存在，则提示错误
    """
    conn = get_db_connection()
    # 对新密码进行哈希处理
    password_hash = generate_password_hash(new_password)
    
    # 更新密码
    cursor = conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (password_hash, username)
    )
    conn.commit()
    
    # 检查是否成功更新
    if cursor.rowcount > 0:
        print(f"用户 '{username}' 的密码已重置")
    else:
        print(f"错误：用户 '{username}' 不存在")
    conn.close()


def show_help():
    """
    显示帮助信息
    打印所有可用命令及使用示例
    """
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


def main():
    """
    主函数
    解析命令行参数并调用相应的功能函数
    """
    # 如果没有提供命令参数，显示帮助信息
    if len(sys.argv) < 2:
        show_help()
        return

    # 获取命令（第一个参数）
    command = sys.argv[1].lower()

    # 根据命令执行相应操作
    if command == 'help':
        # 显示帮助
        show_help()
    
    elif command == 'list':
        # 列出所有用户
        list_users()
    
    elif command == 'add':
        # 添加新用户
        # 需要至少4个参数：脚本名、命令、用户名、密码
        if len(sys.argv) < 4:
            print("用法: python gzb_admin.py add <用户名> <密码> [--admin]")
            return
        username = sys.argv[2]
        password = sys.argv[3]
        # 检查是否有 --admin 标志
        is_admin = '--admin' in sys.argv
        create_user(username, password, is_admin)
    
    elif command == 'del':
        # 删除用户
        # 需要至少3个参数：脚本名、命令、用户名
        if len(sys.argv) < 3:
            print("用法: python gzb_admin.py del <用户名>")
            return
        username = sys.argv[2]
        delete_user(username)
    
    elif command == 'reset':
        # 重置密码
        # 需要至少4个参数：脚本名、命令、用户名、新密码
        if len(sys.argv) < 4:
            print("用法: python gzb_admin.py reset <用户名> <新密码>")
            return
        username = sys.argv[2]
        new_password = sys.argv[3]
        reset_password(username, new_password)
    
    else:
        # 未知命令
        print(f"未知命令: {command}")
        show_help()


# 当作为脚本直接运行时，执行主函数
if __name__ == '__main__':
    main()
