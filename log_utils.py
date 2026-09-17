"""兼容入口：实现已迁移到 core.log_utils。"""
import sys
from core import log_utils as _module
sys.modules[__name__] = _module
