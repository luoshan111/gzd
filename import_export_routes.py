"""兼容入口：实现已迁移到 routes.import_export_routes。"""
import sys
from routes import import_export_routes as _module
sys.modules[__name__] = _module
