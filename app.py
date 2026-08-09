"""员工信息管理系统 Flask 应用入口。

本文件只负责应用初始化、全局错误处理和路由模块注册；
具体业务按认证、页面、员工、Excel 和管理员功能拆分到独立模块。
"""

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import config
from app_common import api_err
from admin_routes import register_admin_routes
from auth_routes import register_auth_routes
from employee_routes import register_employee_routes
from import_export_routes import register_import_export_routes
from agent_routes import register_agent_routes
from log_utils import setup_logging, sys_log
from page_routes import register_page_routes
from db import init_db

# 日志和数据库初始化必须在路由注册前完成，确保导入 app 的启动方式也可用。
setup_logging()
init_db()

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024


@app.errorhandler(404)
def not_found(error):
    """统一处理不存在的资源：API 返回 JSON，页面回到主页。"""
    if request.path.startswith('/api/'):
        return api_err('接口不存在', status=404)
    from flask import redirect, url_for
    return redirect(url_for('index'))


@app.errorhandler(413)
def request_too_large(error):
    """上传超过 MAX_CONTENT_LENGTH 时返回统一的 413 响应。"""
    return api_err('文件过大，最大支持 5MB', status=413)


@app.errorhandler(Exception)
def handle_exception(error):
    """兜底异常处理：API 统一返回 500，页面保留简单错误响应。"""
    if isinstance(error, HTTPException):
        if request.path.startswith('/api/'):
            return api_err(error.description, status=error.code or 500)
        return error
    sys_log.exception('请求处理出现未捕获异常: %s %s', request.method, request.path)
    if request.path.startswith('/api/'):
        return api_err('服务器内部错误', status=500)
    return '服务器内部错误', 500


# 路由注册保持集中管理，便于快速查看应用提供的功能模块。
register_auth_routes(app)
register_page_routes(app)
register_employee_routes(app)
register_import_export_routes(app)
register_admin_routes(app)
register_agent_routes(app)


if __name__ == '__main__':
    app.run(debug=config.DEBUG, host='0.0.0.0', port=config.PORT)
