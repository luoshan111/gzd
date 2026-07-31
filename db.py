"""
数据库访问层
集中管理 SQLite 连接、建表语句和常用查询助手，
供 Flask 应用与各个命令行工具共用，避免重复代码。

用法示例：
    from db import init_db, query_all, query_one, execute

    init_db()
    rows = query_all("SELECT * FROM employees")
    row  = query_one("SELECT * FROM users WHERE username = ?", (name,))
    n    = execute("DELETE FROM employees WHERE real_name = ?", (name,))  # 返回受影响行数
"""

import sqlite3
from contextlib import contextmanager

from pypinyin import lazy_pinyin, Style

import config

# ---------------------------------------------------------------------------
# 表结构（唯一权威定义，init_db 与各工具共用）
# ---------------------------------------------------------------------------

EMPLOYEES_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS employees(
        real_name TEXT PRIMARY KEY,    -- 姓名，主键
        id_number TEXT,                -- 身份证号
        bank_account TEXT,             -- 银行账号
        bank_address TEXT,             -- 银行地址
        phone TEXT,                    -- 电话号码
        sx TEXT,                       -- 拼音首字母，用于搜索
        deleted INTEGER DEFAULT 0,     -- 软删除标记：0 正常，1 已删除
        deleted_at TIMESTAMP,          -- 软删除时间（审计用）
        deleted_by TEXT                -- 删除操作人用户名（审计用）
    )
'''

USERS_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,       -- 用户ID，自增
        username TEXT UNIQUE NOT NULL,              -- 用户名，唯一
        password_hash TEXT NOT NULL,                -- 密码哈希值
        is_admin INTEGER DEFAULT 0,                 -- 是否管理员，0否1是
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- 创建时间
    )
'''

# 员工表索引：加速按"未删除 + 拼音首字母"的查询
# （注意：LIKE '%xx%' 前导通配符的模糊搜索无法使用索引，全表扫描对内部小数据量可接受）
EMPLOYEES_SX_INDEX = '''
    CREATE INDEX IF NOT EXISTS idx_employees_deleted_sx
    ON employees(deleted, sx)
'''


# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    """获取数据库连接，查询结果可通过列名访问。"""
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session(commit: bool = False):
    """
    连接上下文管理器：自动关闭连接；commit=True 时正常结束后自动提交。
    注意：SELECT 不需要 commit；写操作请使用 commit=True。
    """
    conn = get_connection()
    try:
        yield conn
        if commit:
            conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 通用查询/执行助手（覆盖大多数简单场景，免去手动开关连接）
# ---------------------------------------------------------------------------

def query_all(sql: str, params: tuple = ()) -> list:
    """执行查询，返回 dict 列表。"""
    with db_session() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()):
    """执行查询，返回单个 dict；无结果时返回 None。"""
    with db_session() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple = ()) -> int:
    """执行写操作（INSERT/UPDATE/DELETE）并提交，返回受影响行数。"""
    with db_session(commit=True) as conn:
        cursor = conn.execute(sql, params)
        return cursor.rowcount


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    创建 employees（员工信息）和 users（登录用户）表及索引（如不存在），
    并对旧版本数据库执行幂等迁移。
    注意顺序：必须先迁移补列，再创建引用新列的索引。
    """
    with db_session(commit=True) as conn:
        conn.execute(EMPLOYEES_SCHEMA)
        conn.execute(USERS_SCHEMA)
        _migrate_employees(conn)
        conn.execute(EMPLOYEES_SX_INDEX)


def _migrate_employees(conn: sqlite3.Connection) -> None:
    """为旧库 employees 表补充软删除相关列（已存在则跳过，可反复执行）。"""
    existing = {row['name'] for row in conn.execute("PRAGMA table_info(employees)")}
    if 'deleted' not in existing:
        conn.execute("ALTER TABLE employees ADD COLUMN deleted INTEGER DEFAULT 0")
    if 'deleted_at' not in existing:
        conn.execute("ALTER TABLE employees ADD COLUMN deleted_at TIMESTAMP")
    if 'deleted_by' not in existing:
        conn.execute("ALTER TABLE employees ADD COLUMN deleted_by TEXT")


# ---------------------------------------------------------------------------
# 领域工具
# ---------------------------------------------------------------------------

def get_pinyin_sx(name: str) -> str:
    """获取中文姓名的拼音首字母，如 "张三" -> "zs"。"""
    result = lazy_pinyin(name, style=Style.FIRST_LETTER)
    return ''.join(char.lower() for char in result)


def escape_like(keyword: str) -> str:
    """
    转义 LIKE 模式中的特殊字符（\、%、_），
    使关键词按字面匹配；SQL 中需配合 ESCAPE '\\' 使用。
    """
    return keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


# ---------------------------------------------------------------------------
# 分页查询
# ---------------------------------------------------------------------------

def query_paginated(sql: str, params: tuple = (), page: int = 1, page_size: int = 20) -> dict:
    """执行分页查询，返回数据、总数和分页信息。"""
    count_sql = f"SELECT COUNT(*) AS total FROM ({sql}) AS paged_query"
    with db_session() as conn:
        total = conn.execute(count_sql, params).fetchone()['total']
        offset = (page - 1) * page_size
        paginated_sql = f"{sql} LIMIT ? OFFSET ?"
        rows = [
            dict(row)
            for row in conn.execute(
                paginated_sql, params + (page_size, offset)
            ).fetchall()
        ]

    pages = max(1, (total + page_size - 1) // page_size)
    return {
        'data': rows,
        'total': total,
        'page': page,
        'page_size': page_size,
        'pages': pages,
    }
