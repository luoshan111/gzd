"""兼容入口：实现已迁移到 core.db。"""
import sys
from core import db as _module
sys.modules[__name__] = _module
