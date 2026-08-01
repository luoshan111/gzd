"""数据库备份组件。

备份只通过管理员页面按钮或 gzb_backup.py 手动触发，不在应用启动时自动执行。
"""

import logging
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import config

backup_log = logging.getLogger('system')
_BACKUP_FILENAME_RE = re.compile(r'^[A-Za-z0-9_.-]+_[0-9]{8}_[0-9]{6}_[0-9]{6}\.db$')


def _backup_prefix() -> str:
    """返回备份文件使用的数据库名称前缀。"""
    return Path(config.DB_PATH).stem


def _backup_files() -> list[Path]:
    """按生成时间倒序读取当前数据库对应的备份文件。"""
    backup_dir = Path(config.BACKUP_DIR)
    if not backup_dir.exists():
        return []
    return sorted(
        backup_dir.glob(f'{_backup_prefix()}_*.db'),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def cleanup_backups() -> int:
    """清理超出保留数量的旧备份，返回实际删除数量。"""
    deleted = 0
    for backup_path in _backup_files()[config.BACKUP_RETENTION:]:
        try:
            backup_path.unlink()
            deleted += 1
        except FileNotFoundError:
            continue
        except OSError:
            backup_log.exception('删除旧数据库备份失败: %s', backup_path)
    return deleted


def create_backup() -> Path:
    """创建并校验一个 SQLite 一致性备份，返回备份文件路径。"""
    source_path = Path(config.DB_PATH).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f'数据库文件不存在: {source_path}')

    backup_dir = Path(config.BACKUP_DIR).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup_path = backup_dir / f'{_backup_prefix()}_{timestamp}.db'
    temporary_path = backup_dir / f'.{backup_path.name}.tmp'

    source_connection = None
    backup_connection = None
    try:
        # 使用 SQLite 在线备份接口，避免直接复制运行中的数据库文件。
        source_connection = sqlite3.connect(str(source_path), timeout=30)
        backup_connection = sqlite3.connect(str(temporary_path), timeout=30)
        with backup_connection:
            source_connection.backup(backup_connection)

        # 备份文件必须通过完整性检查后才能对外展示。
        result = backup_connection.execute('PRAGMA integrity_check').fetchone()
        if not result or result[0] != 'ok':
            raise sqlite3.DatabaseError(f'备份完整性校验失败: {result}')

        backup_connection.close()
        backup_connection = None
        os.replace(temporary_path, backup_path)
        removed = cleanup_backups()
        backup_log.info('管理员手动创建数据库备份: %s，清理旧备份 %s 个', backup_path, removed)
        return backup_path
    except Exception:
        backup_log.exception('数据库备份失败: %s', source_path)
        raise
    finally:
        if source_connection is not None:
            source_connection.close()
        if backup_connection is not None:
            backup_connection.close()
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def list_backups() -> list[dict]:
    """返回备份页面使用的文件信息，不暴露服务器绝对路径。"""
    result = []
    for backup_path in _backup_files():
        stat = backup_path.stat()
        result.append({
            'filename': backup_path.name,
            'size': stat.st_size,
            'size_text': _format_size(stat.st_size),
            'created_at': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        })
    return result


def get_backup_path(filename: str) -> Path | None:
    """校验备份文件名并返回安全路径，阻止路径穿越和任意文件下载。"""
    if not filename or Path(filename).name != filename:
        return None
    if not _BACKUP_FILENAME_RE.fullmatch(filename):
        return None
    if not filename.startswith(f'{_backup_prefix()}_'):
        return None
    backup_path = Path(config.BACKUP_DIR).resolve() / filename
    return backup_path if backup_path.is_file() else None


def _format_size(size: int) -> str:
    """将字节数转换为备份列表中的可读大小。"""
    if size < 1024:
        return f'{size} B'
    if size < 1024 * 1024:
        return f'{size / 1024:.1f} KB'
    return f'{size / (1024 * 1024):.1f} MB'
