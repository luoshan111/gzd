"""
集中配置模块
所有路径/密钥均可通过环境变量覆盖，默认值保持与原项目一致，开箱即用。
也可以在项目根目录创建 .env 文件集中设置（参考 .env.example），真实环境变量优先。

环境变量一览：
    GZD_SECRET_KEY         Flask session 密钥（生产环境务必设置）
    GZD_DB_PATH            SQLite 数据库文件路径
    GZD_INPUT_XLSX         批量导出的输入 Excel（姓名列表）
    GZD_OUTPUT_XLSX        命令行脚本 gzb_output.py 的输出 Excel
    GZD_PORT               服务端口，默认 5001
    GZD_DEBUG              是否开启调试模式，默认开（设为 0 关闭）
    GZD_LOG_DIR            日志文件目录（按天滚动，保留 30 天）
    GZD_BACKUP_DIR        数据库备份目录，默认 backups/
    GZD_BACKUP_RETENTION  保留备份文件数量，默认 10 个
    GZD_AGENT_API_KEY      AI 助手的模型服务密钥（也可直接设置 OPENAI_API_KEY）
    GZD_AGENT_BASE_URL     AI 助手的接口地址（OpenAI 兼容格式），未设置时用 OpenAI 官方
    GZD_AGENT_MODEL        AI 助手使用的模型，默认 gpt-4o-mini
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv() -> None:
    """读取项目根目录的 .env 文件（每行 KEY=VALUE），不覆盖已存在的环境变量。

    兼容记事本保存的 UTF-8（含 BOM）和 ANSI/GBK 编码。
    """
    path = os.path.join(BASE_DIR, '.env')
    if not os.path.exists(path):
        return
    try:
        text = open(path, encoding='utf-8-sig').read()
    except UnicodeDecodeError:
        text = open(path, encoding='gb18030').read()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _env_path(env_name: str, default_filename: str) -> str:
    """读取环境变量中的路径，未设置时回退到项目目录下的默认文件名。"""
    return os.environ.get(env_name, os.path.join(BASE_DIR, default_filename))


# Flask session 加密密钥（生产环境请通过 GZD_SECRET_KEY 设置随机值）
SECRET_KEY = os.environ.get('GZD_SECRET_KEY', 'gongzidan_secret_key_2026')

# 数据库与 Excel 文件路径
# 网页导出在内存中直接返回文件流，不再落盘；OUTPUT_XLSX 仅供命令行脚本 gzb_output.py 使用。
DB_PATH = _env_path('GZD_DB_PATH', 'data/sjk.db')
INPUT_XLSX = _env_path('GZD_INPUT_XLSX', 'data/input.xlsx')
OUTPUT_XLSX = _env_path('GZD_OUTPUT_XLSX', 'data/output.xlsx')

# 服务运行参数
PORT = int(os.environ.get('GZD_PORT', '5001'))
DEBUG = os.environ.get('GZD_DEBUG', '1') != '0'

# 日志目录与当前日志文件（按天滚动：app.log 为当天，历史为 app.log.YYYY-MM-DD）
LOG_DIR = os.environ.get('GZD_LOG_DIR', os.path.join(BASE_DIR, 'logs'))
LOG_FILE = os.path.join(LOG_DIR, 'app.log')

# 数据库备份参数：备份只由管理员在页面或命令行手动触发
BACKUP_DIR = _env_path('GZD_BACKUP_DIR', 'backups')
BACKUP_RETENTION = max(1, int(os.environ.get('GZD_BACKUP_RETENTION', '10')))

# AI Agent 配置（agent_service.py 从这里读取，此为唯一定义处）
# 通过环境变量设置：GZD_AGENT_API_KEY / GZD_AGENT_MODEL / GZD_AGENT_BASE_URL
AGENT_API_KEY = os.environ.get('GZD_AGENT_API_KEY') or os.environ.get('OPENAI_API_KEY') or ''
AGENT_MODEL = os.environ.get('GZD_AGENT_MODEL') or 'gpt-4o-mini'
# 未设置时保持 None，OpenAI 客户端会自动使用官方接口地址
AGENT_BASE_URL = os.environ.get('GZD_AGENT_BASE_URL') or None
