"""兼容入口：实现已迁移到 routes.auth_routes。"""
import sys
from routes import auth_routes as _module
sys.modules[__name__] = _module
