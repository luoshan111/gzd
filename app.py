"""
员工信息管理系统 - Flask 主应用
功能：员工信息的增删改查、Excel 导入预览/导出、用户登录认证、后台用户管理

启动方式（两种均可）：
    python app.py
    python -c "from app import app; app.run(port=5001, debug=True, host='0.0.0.0')"
"""

import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, jsonify,
                   send_file, redirect, url_for, session)
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

import config
from db import init_db, query_all, query_one, execute, get_pinyin_sx, escape_like
from excel_utils import (read_names, export_employees, IMPORT_COLUMNS,
                         read_employee_excel, classify_import_rows,
                         summarize_import_rows, import_employee_rows)
from log_utils import setup_logging, read_logs, sys_log, db_log

# 对外返回的员工字段（不含 deleted/deleted_at 等内部审计字段）
EMPLOYEE_COLUMNS = 'real_name, id_number, bank_account, bank_address, phone, sx'
# 回收站返回字段（额外包含删除时间、删除人，用于审计展示）
RECYCLE_COLUMNS = EMPLOYEE_COLUMNS + ', deleted_at, deleted_by'
# 上传导入允许的扩展名（.xls 旧格式需要额外的 xlrd 依赖，暂不支持）
ALLOWED_UPLOAD_EXTENSIONS = {'.xlsx'}

# ---------------------------------------------------------------------------
# 日志：系统日志（system.log）与数据库改动日志（database.log），按天滚动各保留 30 天
# ---------------------------------------------------------------------------
setup_logging()

# ---------------------------------------------------------------------------
# 应用实例与初始化
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
# 上传文件大小上限 5MB（员工清单场景足够，防止超大文件占内存）
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

# 模块导入时即确保数据表存在，
# 这样 README 推荐的 `from app import app` 启动方式也不会漏掉建表步骤。
init_db()


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def api_ok(message: str = '', **extra):
    """统一的成功响应格式。"""
    return jsonify({'success': True, 'message': message, **extra})


def api_err(message: str, status: int = 200, **extra):
    """
    统一的失败响应格式。
    业务错误默认仍返回 HTTP 200（前端按 success 字段判断），
    权限/资源类错误使用对应的 HTTP 状态码。
    """
    return jsonify({'success': False, 'message': message, **extra}), status


def _login_required_response():
    """未登录时：API 请求返回 JSON 错误，页面请求重定向到登录页。"""
    if request.is_json or request.path.startswith('/api/'):
        return jsonify({'success': False, 'message': '请先登录', 'need_login': True})
    return redirect(url_for('login'))


def login_required(f):
    """登录验证装饰器：保护需要登录才能访问的路由。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return _login_required_response()
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """管理员权限验证装饰器：先查登录，再查管理员身份。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return _login_required_response()
        if not session.get('is_admin'):
            return api_err('需要管理员权限', status=403)
        return f(*args, **kwargs)
    return decorated_function


def _get_employee_fields(data: dict) -> dict:
    """从请求 JSON 中提取并清洗员工字段。"""
    return {
        'real_name': data.get('real_name', '').strip(),
        'id_number': data.get('id_number', '').strip(),
        'bank_account': data.get('bank_account', '').strip(),
        'bank_address': data.get('bank_address', '').strip(),
        'phone': data.get('phone', '').strip(),
    }


# ---------------------------------------------------------------------------
# 全局错误处理
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return api_err('接口不存在', status=404)
    return redirect(url_for('index'))


@app.errorhandler(413)
def request_too_large(e):
    """上传超过 MAX_CONTENT_LENGTH 时的友好提示。"""
    return api_err('文件过大，最大支持 5MB', status=413)


@app.errorhandler(Exception)
def handle_exception(e):
    """兜底异常处理：框架级异常原样放行，其余记录日志并返回统一错误。"""
    if isinstance(e, HTTPException):
        return e
    sys_log.exception('请求处理出现未捕获异常: %s %s', request.method, request.path)
    if request.path.startswith('/api/'):
        return api_err(f'服务器内部错误: {e}', status=500)
    return '服务器内部错误', 500


# ==================== 登录相关路由 ====================

@app.route('/login')
def login():
    """登录页面：已登录用户直接跳转主页。"""
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    """登录接口：验证用户名密码，成功后写入 session。"""
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return api_err('请输入用户名和密码')

    user = query_one(
        "SELECT id, username, password_hash, is_admin FROM users WHERE username = ?",
        (username,)
    )

    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_admin'] = user['is_admin']
        sys_log.info('用户 %s 登录成功', username)
        return api_ok('登录成功', is_admin=user['is_admin'])

    sys_log.info('用户 %s 登录失败', username)
    return api_err('用户名或密码错误')


@app.route('/api/logout', methods=['POST'])
def api_logout():
    """登出接口：清除 session。"""
    sys_log.info('用户 %s 退出登录', session.get('username'))
    session.clear()
    return api_ok('已退出登录')


@app.route('/api/check-login')
def check_login():
    """查询当前登录状态。"""
    if 'user_id' in session:
        return jsonify({
            'success': True,
            'logged_in': True,
            'username': session.get('username'),
            'is_admin': session.get('is_admin', False)
        })
    return jsonify({'success': True, 'logged_in': False})


# ==================== 页面路由 ====================

@app.route('/')
@login_required
def index():
    """主页。"""
    return render_template('index.html')


@app.route('/admin')
@admin_required
def admin_page():
    """管理员后台页面。"""
    return render_template('admin.html')


@app.route('/recycle-bin')
@login_required
def recycle_bin_page():
    """回收站页面：查看、恢复已删除的员工记录。"""
    return render_template('recycle_bin.html')


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
        "AND (real_name LIKE ? ESCAPE '\\' OR sx LIKE ? ESCAPE '\\')",
        (keyword, keyword)
    )

    if results:
        return api_ok(data=results)
    return api_err('未找到匹配的记录')


@app.route('/api/employees', methods=['GET'])
@login_required
def get_employees():
    """获取全部在职员工列表（按姓名排序，不含已软删除记录）。"""
    return api_ok(data=query_all(
        f"SELECT {EMPLOYEE_COLUMNS} FROM employees WHERE deleted = 0 ORDER BY real_name"
    ))


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
    fields = _get_employee_fields(data)

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
        # 同名记录曾被软删除：恢复并覆盖为新内容，清除删除标记
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
    return api_err('未找到该员工，可能已被删除')


# ==================== 回收站 API ====================

@app.route('/api/recycle-bin', methods=['GET'])
@login_required
def get_recycle_bin():
    """获取回收站列表：已软删除的员工，按删除时间倒序。"""
    rows = query_all(
        f"SELECT {RECYCLE_COLUMNS} FROM employees "
        "WHERE deleted = 1 ORDER BY deleted_at DESC"
    )
    return api_ok(data=rows)


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
    return api_err('回收站中未找到该员工')


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
    return api_err('回收站中未找到该员工')


# ==================== Excel 上传导入 API ====================

@app.route('/api/import-preview', methods=['POST'])
@login_required
def import_preview():
    """
    上传 Excel 并返回校验预览报告（只解析不写库）。
    multipart 字段: file（.xlsx，最大 5MB，内存中解析不落盘）
    返回: rows（每行含数据、status、messages）+ summary（分类统计）
    """
    file = request.files.get('file')
    if not file or not file.filename:
        return api_err('请选择要上传的 Excel 文件')

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return api_err('仅支持 .xlsx 格式文件')

    try:
        rows = read_employee_excel(file.stream)
    except ValueError as e:
        return api_err(str(e))
    except Exception as e:
        sys_log.warning('导入预览解析失败: %s', e)
        return api_err('文件解析失败，请确认是有效的 .xlsx 文件')

    if not rows:
        return api_err('文件中没有数据行')

    rows = classify_import_rows(rows)
    return api_ok(rows=rows, summary=summarize_import_rows(rows))


@app.route('/api/import-confirm', methods=['POST'])
@login_required
def import_confirm():
    """
    确认导入：接收预览通过的行数据，服务端重新清洗校验后单事务写入。
    JSON: {"rows": [{real_name, id_number, bank_account, bank_address, phone}, ...]}
    说明: 不信任前端传入的 status，一切以服务端重新分类为准。
    """
    data = request.get_json(silent=True) or {}
    raw_rows = data.get('rows', [])
    if not raw_rows:
        return api_err('没有可导入的数据')

    # 服务端复核：重新清洗字段并分类（验证 + 打标）
    cleaned = []
    for raw in raw_rows:
        row = {'_row': raw.get('_row', 0)}
        for field in IMPORT_COLUMNS:
            row[field] = str(raw.get(field, '') or '').strip()
        cleaned.append(row)

    rows = classify_import_rows(cleaned)
    result = import_employee_rows(rows)

    db_log.info('用户 %s 导入员工: %s', session.get('username'), result)
    return api_ok('导入完成', **result)


# ==================== Excel 导出 API ====================

@app.route('/api/export', methods=['POST'])
@login_required
def export_excel():
    """读取 input.xlsx 中的姓名列表，匹配数据库信息后导出到 output.xlsx。"""
    try:
        names = read_names(config.INPUT_XLSX)
    except FileNotFoundError as e:
        return api_err(str(e))

    if not names:
        return api_err('input.xlsx 中没有姓名数据')

    try:
        total, matched = export_employees(names, config.OUTPUT_XLSX)
    except Exception as e:
        sys_log.exception('导出 Excel 失败')
        return api_err(f'导出失败: {e}')

    sys_log.info('用户 %s 批量导出 Excel: 共 %s 条，匹配 %s 条',
                session.get('username'), total, matched)
    return api_ok('导出成功', file=config.OUTPUT_XLSX, total=total, matched=matched)


@app.route('/api/export-manual', methods=['POST'])
@login_required
def export_manual_excel():
    """接收前端输入的姓名列表，匹配数据库信息后导出到 shuchu.xlsx。"""
    data = request.get_json(silent=True) or {}
    names = [str(n).strip() for n in data.get('names', []) if str(n).strip()]

    if not names:
        return api_err('请提供姓名列表')

    try:
        total, matched = export_employees(names, config.MANUAL_OUTPUT_XLSX)
    except Exception as e:
        sys_log.exception('手动导出 Excel 失败')
        return api_err(f'导出失败: {e}')

    sys_log.info('用户 %s 手动导出 Excel: 共 %s 条，匹配 %s 条',
                session.get('username'), total, matched)
    return api_ok('导出成功', file=config.MANUAL_OUTPUT_XLSX, total=total, matched=matched)


@app.route('/api/input-preview')
@login_required
def input_preview():
    """预览 input.xlsx 前 20 行姓名，用于前端展示。"""
    try:
        names = read_names(config.INPUT_XLSX, limit=20)
    except FileNotFoundError as e:
        return api_err(str(e))
    except Exception as e:
        sys_log.exception('读取 input.xlsx 失败')
        return api_err(str(e))

    return api_ok(data=[{'姓名': n} for n in names], columns=['姓名'])


@app.route('/api/download/<filename>')
@login_required
def download_file(filename):
    """
    下载导出的 Excel 文件。
    仅允许下载白名单内的文件（output.xlsx / shuchu.xlsx），防止路径穿越攻击。
    """
    path = config.ALLOWED_DOWNLOADS.get(filename)
    if not path or not os.path.exists(path):
        return api_err('文件不存在或不允许下载', status=404)
    sys_log.info('用户 %s 下载文件: %s', session.get('username'), filename)
    return send_file(path, as_attachment=True)


# ==================== 操作日志 API ====================

@app.route('/api/logs')
@admin_required
def get_logs():
    """
    操作日志查询（仅管理员）。
    参数: category(system 系统日志 / db 数据库改动日志，默认 system)
          date(YYYY-MM-DD，默认今天) / level(INFO/WARNING/ERROR/DEBUG)
          / keyword / page / page_size(默认50，上限200)
    返回: logs（倒序，最新在前）+ total/pages/stats/dates（可用日期列表）
    """
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

    return api_ok(**read_logs(category=category, date=date, level=level,
                              keyword=keyword, page=page, page_size=page_size))


# ==================== 管理员功能 API ====================

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def get_users():
    """获取所有登录用户列表。"""
    users = query_all(
        "SELECT id, username, is_admin, created_at FROM users ORDER BY id"
    )
    return api_ok(data=users)


@app.route('/api/admin/user', methods=['POST'])
@admin_required
def create_user():
    """创建新用户。"""
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    is_admin = 1 if data.get('is_admin') else 0

    if not username or not password:
        return api_err('用户名和密码不能为空')
    if len(password) < 4:
        return api_err('密码至少4位')

    try:
        execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), is_admin)
        )
    except sqlite3.IntegrityError:
        return api_err('用户名已存在')

    db_log.info('管理员 %s 创建用户 %s', session.get('username'), username)
    return api_ok('用户创建成功')


@app.route('/api/admin/user/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """删除用户（不能删除自己的账户）。"""
    if user_id == session.get('user_id'):
        return api_err('不能删除自己的账户')

    deleted = execute("DELETE FROM users WHERE id = ?", (user_id,))
    if not deleted:
        return api_err('用户不存在')

    db_log.info('管理员 %s 删除用户 id=%s', session.get('username'), user_id)
    return api_ok('用户删除成功')


@app.route('/api/admin/user/<int:user_id>/password', methods=['PUT'])
@admin_required
def reset_user_password(user_id):
    """重置指定用户的密码。"""
    data = request.get_json(silent=True) or {}
    password = data.get('password', '')

    if not password or len(password) < 4:
        return api_err('密码至少4位')

    updated = execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), user_id)
    )
    if not updated:
        return api_err('用户不存在')

    db_log.info('管理员 %s 重置用户 id=%s 的密码', session.get('username'), user_id)
    return api_ok('密码重置成功')


# ==================== 应用启动 ====================

if __name__ == '__main__':
    # host='0.0.0.0' 允许局域网访问；端口/调试模式可用环境变量覆盖
    app.run(debug=config.DEBUG, host='0.0.0.0', port=config.PORT)
