"""兼容入口：实现已迁移到 core.config。"""
import sys
from core import config as _module
sys.modules[__name__] = _module
