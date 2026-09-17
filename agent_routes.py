"""兼容入口：实现已迁移到 routes.agent_routes。"""
import sys
from routes import agent_routes as _module
sys.modules[__name__] = _module
