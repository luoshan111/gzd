"""兼容入口：实现已迁移到 routes.page_routes。"""
import sys
from routes import page_routes as _module
sys.modules[__name__] = _module
