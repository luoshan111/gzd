"""兼容入口：实现已迁移到 routes.employee_routes。"""
import sys
from routes import employee_routes as _module
sys.modules[__name__] = _module
