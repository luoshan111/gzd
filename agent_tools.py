import json
from db import query_all, query_one, execute, get_pinyin_sx, query_paginated
from app_common import EMPLOYEE_COLUMNS
from excel_utils import export_employees, read_employee_excel, classify_import_rows, import_employee_rows, summarize_import_rows
from backup_utils import create_backup, list_backups
from log_utils import read_logs
import config

# ── 工具注册表 ──────────────────────────────────────────────

TOOLS = []

def tool(name, description, parameters):
    """注册一个工具函数。"""
    def decorator(fn):
        TOOLS.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            }
        })
        fn._tool_name = name
        return fn
    return decorator

# ── 工具实现 ────────────────────────────────────────────────

@tool(
    name="search_employee",
    description="按姓名或拼音首字母搜索在职员工，返回匹配列表。",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "搜索关键词（姓名或拼音首字母）"}
        },
        "required": ["keyword"]
    }
)
def search_employee(keyword: str) -> dict:
    from db import escape_like
    kw = f"%{escape_like(keyword)}%"
    rows = query_all(
        f"SELECT {EMPLOYEE_COLUMNS} FROM employees WHERE deleted=0 "
        "AND (real_name LIKE ? ESCAPE '\\' OR sx LIKE ? ESCAPE '\\') "
        "ORDER BY real_name",
        (kw, kw)
    )
    return {"found": len(rows), "employees": rows}

@tool(
    name="get_employee",
    description="查询单个员工的完整信息（按精确姓名）。",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "员工姓名（精确匹配）"}
        },
        "required": ["name"]
    }
)
def get_employee(name: str) -> dict:
    row = query_one(f"SELECT {EMPLOYEE_COLUMNS} FROM employees WHERE real_name=? AND deleted=0", (name,))
    if row:
        return {"found": True, "employee": row}
    return {"found": False, "message": f"未找到员工「{name}」"}

@tool(
    name="add_employee",
    description="新增一个员工。如果同名员工已存在则返回错误。",
    parameters={
        "type": "object",
        "properties": {
            "real_name": {"type": "string", "description": "姓名（必填）"},
            "id_number": {"type": "string", "description": "身份证号"},
            "bank_account": {"type": "string", "description": "银行账号"},
            "bank_address": {"type": "string", "description": "银行地址/开户行"},
            "phone": {"type": "string", "description": "电话号码"}
        },
        "required": ["real_name"]
    }
)
def add_employee(real_name: str, id_number: str = "", bank_account: str = "", bank_address: str = "", phone: str = "") -> dict:
    existing = query_one("SELECT deleted FROM employees WHERE real_name=?", (real_name,))
    if existing and not existing["deleted"]:
        return {"success": False, "message": f"员工「{real_name}」已存在，请用更新功能修改信息"}
    sx = get_pinyin_sx(real_name)
    if existing and existing["deleted"]:
        execute(
            "UPDATE employees SET id_number=?, bank_account=?, bank_address=?, phone=?, sx=?, deleted=0, deleted_at=NULL, deleted_by=NULL WHERE real_name=?",
            (id_number, bank_account, bank_address, phone, sx, real_name)
        )
        return {"success": True, "message": f"已恢复并更新员工「{real_name}」"}
    execute(
        "INSERT INTO employees (real_name, id_number, bank_account, bank_address, phone, sx) VALUES (?,?,?,?,?,?)",
        (real_name, id_number, bank_account, bank_address, phone, sx)
    )
    return {"success": True, "message": f"已添加员工「{real_name}」"}

@tool(
    name="update_employee",
    description="更新一个在职员工的信息（只更新传入的字段，未传入的字段保持不变）。",
    parameters={
        "type": "object",
        "properties": {
            "real_name": {"type": "string", "description": "姓名（必填，用于定位员工）"},
            "id_number": {"type": "string", "description": "新的身份证号"},
            "bank_account": {"type": "string", "description": "新的银行账号"},
            "bank_address": {"type": "string", "description": "新的银行地址/开户行"},
            "phone": {"type": "string", "description": "新的电话号码"}
        },
        "required": ["real_name"]
    }
)
def update_employee(real_name: str, **fields) -> dict:
    existing = query_one(f"SELECT {EMPLOYEE_COLUMNS} FROM employees WHERE real_name=? AND deleted=0", (real_name,))
    if not existing:
        return {"success": False, "message": f"未找到在职员工「{real_name}」"}
    updates = []
    params = []
    for key in ("id_number", "bank_account", "bank_address", "phone"):
        val = fields.get(key)
        if val is not None and val != "":
            updates.append(f"{key}=?")
            params.append(val)
    if not updates:
        return {"success": False, "message": "未提供任何需要更新的字段"}
    params.append(real_name)
    execute(f"UPDATE employees SET {', '.join(updates)} WHERE real_name=? AND deleted=0", tuple(params))
    return {"success": True, "message": f"已更新员工「{real_name}」的信息"}

@tool(
    name="delete_employee",
    description="删除一个员工（软删除，可从回收站恢复）。",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "要删除的员工姓名"}
        },
        "required": ["name"]
    }
)
def delete_employee(name: str) -> dict:
    n = execute("UPDATE employees SET deleted=1, deleted_at=CURRENT_TIMESTAMP WHERE real_name=? AND deleted=0", (name,))
    if n:
        return {"success": True, "message": f"已删除员工「{name}」，可在回收站中恢复"}
    return {"success": False, "message": f"未找到在职员工「{name}」"}

@tool(
    name="restore_employee",
    description="从回收站恢复一个已删除的员工。",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "要恢复的员工姓名"}
        },
        "required": ["name"]
    }
)
def restore_employee(name: str) -> dict:
    n = execute("UPDATE employees SET deleted=0, deleted_at=NULL, deleted_by=NULL WHERE real_name=? AND deleted=1", (name,))
    if n:
        return {"success": True, "message": f"已恢复员工「{name}」"}
    return {"success": False, "message": f"回收站中未找到「{name}」"}

@tool(
    name="list_employees",
    description="获取在职员工列表（分页）。不指定 page 时返回第一页。",
    parameters={
        "type": "object",
        "properties": {
            "page": {"type": "integer", "description": "页码，默认 1"},
            "page_size": {"type": "integer", "description": "每页条数，默认 20，最大 100"}
        }
    }
)
def list_employees(page: int = 1, page_size: int = 20) -> dict:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    result = query_paginated(
        f"SELECT {EMPLOYEE_COLUMNS} FROM employees WHERE deleted=0 ORDER BY real_name",
        page=page, page_size=page_size
    )
    return result

@tool(
    name="list_recycle_bin",
    description="查看回收站中已删除的员工列表。",
    parameters={
        "type": "object",
        "properties": {
            "page": {"type": "integer", "description": "页码，默认 1"},
            "page_size": {"type": "integer", "description": "每页条数，默认 20"}
        }
    }
)
def list_recycle_bin(page: int = 1, page_size: int = 20) -> dict:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    result = query_paginated(
        f"SELECT {EMPLOYEE_COLUMNS}, deleted_at, deleted_by FROM employees WHERE deleted=1 ORDER BY deleted_at DESC",
        page=page, page_size=page_size
    )
    return result

@tool(
    name="export_employees",
    description="按姓名列表导出员工信息到 Excel 文件。返回导出结果摘要。",
    parameters={
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要导出的员工姓名列表"
            }
        },
        "required": ["names"]
    }
)
def export_employees_tool(names: list) -> dict:
    if not names:
        return {"success": False, "message": "请提供要导出的姓名列表"}
    total, matched = export_employees(names, config.MANUAL_OUTPUT_XLSX)
    return {"success": True, "message": f"导出完成，共 {total} 人，匹配到 {matched} 人", "total": total, "matched": matched, "file": "shuchu.xlsx"}

@tool(
    name="batch_update_employees",
    description="批量更新多个员工的字段信息。每个 item 包含 real_name 和要更新的字段。",
    parameters={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "real_name": {"type": "string", "description": "员工姓名"},
                        "id_number": {"type": "string"},
                        "bank_account": {"type": "string"},
                        "bank_address": {"type": "string"},
                        "phone": {"type": "string"}
                    },
                    "required": ["real_name"]
                },
                "description": "要更新的员工列表"
            }
        },
        "required": ["items"]
    }
)
def batch_update_employees(items: list) -> dict:
    success_count = 0
    fail_count = 0
    messages = []
    for item in items:
        name = item.get("real_name", "").strip()
        if not name:
            fail_count += 1
            messages.append("跳过：姓名为空")
            continue
        result = update_employee(name, **{k: v for k, v in item.items() if k != "real_name"})
        if result.get("success"):
            success_count += 1
        else:
            # 尝试新增
            add_result = add_employee(name, **{k: v for k, v in item.items() if k != "real_name"})
            if add_result.get("success"):
                success_count += 1
                messages.append(f"「{name}」不存在，已自动新增")
            else:
                fail_count += 1
                messages.append(f"「{name}」失败: {add_result.get('message','')}")
    return {"success": True, "message": f"批量操作完成：成功 {success_count} 条，失败 {fail_count} 条", "details": messages[:10]}

@tool(
    name="create_backup",
    description="手动创建数据库备份。",
    parameters={"type": "object", "properties": {}}
)
def create_backup_tool() -> dict:
    path = create_backup()
    return {"success": True, "message": f"备份已创建：{path.name}"}

@tool(
    name="get_logs",
    description="查询系统操作日志。",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["system", "db"], "description": "日志类别：system 或 db"},
            "keyword": {"type": "string", "description": "搜索关键词"},
            "date": {"type": "string", "description": "日期，格式 YYYY-MM-DD"}
        }
    }
)
def get_logs_tool(category: str = "system", keyword: str = None, date: str = None) -> dict:
    result = read_logs(category=category, keyword=keyword, date=date, page=1, page_size=20)
    return result

@tool(
    name="count_employees",
    description="统计在职员工总数和回收站员工总数。",
    parameters={"type": "object", "properties": {}}
)
def count_employees() -> dict:
    active = query_one("SELECT COUNT(*) as cnt FROM employees WHERE deleted=0")
    deleted = query_one("SELECT COUNT(*) as cnt FROM employees WHERE deleted=1")
    return {"active": active["cnt"], "deleted": deleted["cnt"]}


def get_tool_definitions() -> list:
    """返回所有工具的 OpenAI function calling 定义。"""
    return TOOLS

def execute_tool(name: str, arguments: dict) -> dict:
    """根据名称执行对应的工具函数。"""
    tool_map = {t._tool_name: t for t in [search_employee, get_employee, add_employee, update_employee, delete_employee, restore_employee, list_employees, list_recycle_bin, export_employees_tool, batch_update_employees, create_backup_tool, get_logs_tool, count_employees]}
    fn = tool_map.get(name)
    if not fn:
        return {"error": f"未知工具: {name}"}
    try:
        return fn(**arguments)
    except Exception as e:
        return {"error": f"执行出错: {str(e)}"}
