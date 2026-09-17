"""兼容入口：实现已迁移到 core.backup_utils。"""
import sys
from core import backup_utils as _module
sys.modules[__name__] = _module
