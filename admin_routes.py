"""兼容入口：实现已迁移到 routes.admin_routes。"""
import sys
from routes import admin_routes as _module
sys.modules[__name__] = _module
