"""
日志模块：日志落盘配置与日志查询。

日志分两类，各自独立文件、按天滚动（保留 30 天）：
- 系统日志       logs/system.log    登录/登出、导出/下载、HTTP 请求、服务异常等
- 数据库改动日志 logs/database.log  员工增删改/恢复/彻底删除、Excel 导入写入、用户管理

历史兼容：旧版单一文件 app.log 视为系统日志，参与日期列表与查询。

日志行格式（前端按此解析）：
    2026-07-27 20:11:32 | INFO | system | 用户 admin 登录成功
"""

import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

import config

LOG_FORMAT = '%(asctime)s | %(levelname)s | %(name)s | %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
# 滚动文件后缀：system.log.2026-07-27
LOG_SUFFIX_FORMAT = '%Y-%m-%d'

# 日志分类：category -> (文件基名, logger 名)
CATEGORY_SYSTEM = 'system'
CATEGORY_DB = 'db'
CATEGORIES = (CATEGORY_SYSTEM, CATEGORY_DB)
_LOG_FILES = {
    CATEGORY_SYSTEM: ('system.log', 'system'),
    CATEGORY_DB: ('database.log', 'db'),
}

# 业务代码直接使用的两个 logger（setup_logging 后才会落盘）
sys_log = logging.getLogger('system')
db_log = logging.getLogger('db')


def setup_logging() -> None:
    """
    配置两类日志：各自按天滚动写文件 + 控制台输出；werkzeug 的 HTTP 请求日志归入系统日志。
    幂等：重复调用不会重复添加 handler
    （Flask debug 模式的 reloader 会两次导入模块，冒烟测试也可能重复调用）。
    """
    os.makedirs(config.LOG_DIR, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    for _, (basename, logger_name) in _LOG_FILES.items():
        lg = logging.getLogger(logger_name)
        lg.setLevel(logging.INFO)
        lg.propagate = False  # 不再冒泡到 root，避免与其他 handler 重复

        # 文件 handler：TimedRotatingFileHandler 是 StreamHandler 的子类，两个判断顺序不能颠倒
        if not any(isinstance(h, TimedRotatingFileHandler) for h in lg.handlers):
            file_handler = TimedRotatingFileHandler(
                os.path.join(config.LOG_DIR, basename),
                when='midnight', backupCount=30, encoding='utf-8'
            )
            file_handler.suffix = LOG_SUFFIX_FORMAT
            file_handler.setFormatter(formatter)
            lg.addHandler(file_handler)

        if not any(isinstance(h, logging.StreamHandler)
                   and not isinstance(h, TimedRotatingFileHandler) for h in lg.handlers):
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            lg.addHandler(console_handler)

    # HTTP 请求日志归入系统日志（共享 system 的 handler，werkzeug 自身不再冒泡）
    # 注意必须显式设级别：werkzeug 默认 NOTSET 会继承 root 的 WARNING，导致 INFO 请求日志被丢弃
    werkzeug_log = logging.getLogger('werkzeug')
    werkzeug_log.setLevel(logging.INFO)
    werkzeug_log.propagate = False
    for h in sys_log.handlers:
        if h not in werkzeug_log.handlers:
            werkzeug_log.addHandler(h)


# ---------------------------------------------------------------------------
# 日志查询
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.now().strftime(LOG_SUFFIX_FORMAT)


def _candidate_basenames(category: str) -> list:
    """返回该类别参与查询的文件基名（系统日志额外兼容旧版 app.log）。"""
    basenames = [_LOG_FILES[category][0]]
    if category == CATEGORY_SYSTEM:
        basenames.append('app.log')
    return basenames


def list_log_dates(category: str = CATEGORY_SYSTEM) -> list:
    """扫描日志目录，返回该类别有日志文件的日期列表（新→旧）。"""
    dates = []
    if not os.path.isdir(config.LOG_DIR):
        return dates
    files = os.listdir(config.LOG_DIR)
    for base in _candidate_basenames(category):
        if base in files:
            dates.append(_today())
        prefix = base + '.'
        for fname in files:
            if fname.startswith(prefix):
                suffix = fname[len(prefix):]
                try:
                    datetime.strptime(suffix, LOG_SUFFIX_FORMAT)
                    dates.append(suffix)
                except ValueError:
                    continue  # 非日期后缀的文件，忽略
    return sorted(set(dates), reverse=True)


def _log_files_for_date(category: str, date_str: str) -> list:
    """返回指定日期该类别实际存在的日志文件路径列表（按优先级排序）。"""
    paths = []
    for base in _candidate_basenames(category):
        if date_str == _today():
            path = os.path.join(config.LOG_DIR, base)
        else:
            path = os.path.join(config.LOG_DIR, f'{base}.{date_str}')
        if os.path.exists(path):
            paths.append(path)
    return paths


def _parse_line(line: str):
    """
    解析一行日志为 dict；非标准行（如 traceback 续行）返回 None，由调用方并入上一条。
    """
    parts = line.rstrip('\n').split(' | ', 3)
    if len(parts) == 4:
        return {'time': parts[0], 'level': parts[1], 'module': parts[2], 'message': parts[3]}
    return None


def read_logs(category: str = CATEGORY_SYSTEM, date: str = None, level: str = None,
              keyword: str = None, page: int = 1, page_size: int = 50) -> dict:
    """
    查询日志：选类别与日期 → 关键词过滤 → 统计各级别数量 → 级别过滤 → 倒序分页。

    返回: {
        logs: [...], total, page, pages, page_size,
        stats: {级别: 数量},   # 统计在级别过滤之前，保证切换级别时徽章数字稳定
        category, date, dates  # 当前类别、当前日期与全部可用日期
    }
    """
    if category not in CATEGORIES:
        category = CATEGORY_SYSTEM
    date = date or _today()

    entries = []
    for path in _log_files_for_date(category, date):
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                entry = _parse_line(line)
                if entry is None:
                    # traceback 等续行：并入上一条日志的消息，保证多行错误完整可见
                    if entries:
                        entries[-1]['message'] += '\n' + line.rstrip('\n')
                    continue
                entries.append(entry)

    if keyword:
        kw = keyword.lower()
        entries = [e for e in entries if kw in e['message'].lower()]

    stats = {}
    for e in entries:
        stats[e['level']] = stats.get(e['level'], 0) + 1

    if level:
        entries = [e for e in entries if e['level'] == level]

    total = len(entries)
    # 多个文件合并后必须按时间重排（如 system.log 与兼容的 app.log），
    # 字符串时间 'YYYY-MM-DD HH:MM:SS' 可直接按字典序比较；倒序后最新在前
    entries.sort(key=lambda e: e['time'], reverse=True)

    page_size = max(1, min(page_size, 200))
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, pages))
    start = (page - 1) * page_size

    return {
        'logs': entries[start:start + page_size],
        'total': total, 'page': page, 'pages': pages, 'page_size': page_size,
        'stats': stats, 'category': category, 'date': date,
        'dates': list_log_dates(category),
    }
