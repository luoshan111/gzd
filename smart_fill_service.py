"""兼容入口：实现已迁移到 services.smart_fill_service。"""
import sys
from services import smart_fill_service as _module
sys.modules[__name__] = _module
