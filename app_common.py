"""应用公共能力：字段常量、统一响应和权限装饰器。"""

from functools import wraps

from flask import jsonify, redirect, request, session, url_for

# API 对外字段白名单：避免把软删除审计字段直接暴露给普通列表接口。
EMPLOYEE_COLUMNS = 'real_name, id_number, bank_account, bank_address, phone, sx'
RECYCLE_COLUMNS = EMPLOYEE_COLUMNS + ', deleted_at, deleted_by'
ALLOWED_UPLOAD_EXTENSIONS = {'.xlsx'}


def api_ok(message: str = '', **extra):
    """返回统一成功响应；成功请求固定使用 HTTP 200。"""
    return jsonify({'success': True, 'message': message, **extra}), 200


def api_err(message: str, status: int = 400, **extra):
    """
    返回统一失败响应。

    状态码约定：400 参数/业务校验失败，401 未登录，403 无权限，
    404 资源不存在，409 资源冲突，413 请求过大，500 服务端异常。
    前端仍可通过 success 字段读取业务结果，HTTP 状态码用于客户端和监控判断。
    """
    return jsonify({'success': False, 'message': message, **extra}), status


def login_required_response():
    """未登录时，API 返回 401 JSON，页面请求跳转到登录页。"""
    if request.is_json or request.path.startswith('/api/'):
        return api_err('请先登录', status=401, need_login=True)
    return redirect(url_for('login'))


def login_required(f):
    """登录验证装饰器：保护需要登录才能访问的页面和 API。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return login_required_response()
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """管理员权限装饰器：未登录返回 401，普通用户返回 403。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return login_required_response()
        if not session.get('is_admin'):
            return api_err('需要管理员权限', status=403)
        return f(*args, **kwargs)
    return decorated_function


def get_employee_fields(data: dict) -> dict:
    """从请求 JSON 提取并清洗员工字段，统一处理空值和首尾空格。"""
    return {
        'real_name': str(data.get('real_name', '') or '').strip(),
        'id_number': str(data.get('id_number', '') or '').strip(),
        'bank_account': str(data.get('bank_account', '') or '').strip(),
        'bank_address': str(data.get('bank_address', '') or '').strip(),
        'phone': str(data.get('phone', '') or '').strip(),
    }
