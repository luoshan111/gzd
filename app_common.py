"""兼容入口：实现已迁移到 core.app_common。"""
import sys
from core import app_common as _module
sys.modules[__name__] = _module
