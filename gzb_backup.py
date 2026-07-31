"""手动创建数据库备份。

用法：python gzb_backup.py
"""

from backup_utils import create_backup
from db import init_db


if __name__ == '__main__':
    init_db()
    backup_path = create_backup()
    print(f'数据库备份完成: {backup_path}')
