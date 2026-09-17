"""兼容入口：实现已迁移到 services.agent_service。"""
import sys
from services import agent_service as _module
sys.modules[__name__] = _module
