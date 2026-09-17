"""兼容入口：实现已迁移到 services.excel_utils。"""
import sys
from services import excel_utils as _module
sys.modules[__name__] = _module
