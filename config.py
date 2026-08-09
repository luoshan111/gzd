"""
集中配置模块
所有路径/密钥均可通过环境变量覆盖，默认值保持与原项目一致，开箱即用。

环境变量一览：
    GZD_SECRET_KEY         Flask session 密钥（生产环境务必设置）
    GZD_DB_PATH            SQLite 数据库文件路径
    GZD_INPUT_XLSX         批量导出的输入 Excel（姓名列表）
    GZD_OUTPUT_XLSX        批量导出的输出 Excel
    GZD_MANUAL_OUTPUT_XLSX 手动导出的输出 Excel
    GZD_PORT               服务端口，默认 5001
    GZD_DEBUG              是否开启调试模式，默认开（设为 0 关闭）
    GZD_LOG_DIR            日志文件目录（按天滚动，保留 30 天）
    GZD_BACKUP_DIR        数据库备份目录，默认 backups/
    GZD_BACKUP_RETENTION  保留备份文件数量，默认 10 个
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env_path(env_name: str, default_filename: str) -> str:
    """读取环境变量中的路径，未设置时回退到项目目录下的默认文件名。"""
    return os.environ.get(env_name, os.path.join(BASE_DIR, default_filename))


# Flask session 加密密钥（生产环境请通过 GZD_SECRET_KEY 设置随机值）
SECRET_KEY = os.environ.get('GZD_SECRET_KEY', 'gongzidan_secret_key_2026')

# 数据库与 Excel 文件路径
DB_PATH = _env_path('GZD_DB_PATH', 'data/sjk.db')
INPUT_XLSX = _env_path('GZD_INPUT_XLSX', 'data/input.xlsx')
OUTPUT_XLSX = _env_path('GZD_OUTPUT_XLSX', 'data/output.xlsx')
MANUAL_OUTPUT_XLSX = _env_path('GZD_MANUAL_OUTPUT_XLSX', 'data/shuchu.xlsx')

# 允许通过 /api/download/<filename> 下载的文件（按文件名白名单，防止路径穿越攻击）
ALLOWED_DOWNLOADS = {
    os.path.basename(OUTPUT_XLSX): OUTPUT_XLSX,
    os.path.basename(MANUAL_OUTPUT_XLSX): MANUAL_OUTPUT_XLSX,
}

# 服务运行参数
PORT = int(os.environ.get('GZD_PORT', '5001'))
DEBUG = os.environ.get('GZD_DEBUG', '1') != '0'

# 日志目录与当前日志文件（按天滚动：app.log 为当天，历史为 app.log.YYYY-MM-DD）
LOG_DIR = os.environ.get('GZD_LOG_DIR', os.path.join(BASE_DIR, 'logs'))
LOG_FILE = os.path.join(LOG_DIR, 'app.log')

# 数据库备份参数：备份只由管理员在页面或命令行手动触发
BACKUP_DIR = _env_path('GZD_BACKUP_DIR', 'backups')
BACKUP_RETENTION = max(1, int(os.environ.get('GZD_BACKUP_RETENTION', '10')))

# AI Agent 配置
# 通过环境变量设置：GZD_AGENT_API_KEY / GZD_AGENT_MODEL / GZD_AGENT_BASE_URL
AGENT_API_KEY = os.environ.get('GZD_AGENT_API_KEY', os.environ.get('OPENAI_API_KEY', ''))
AGENT_MODEL = os.environ.get('GZD_AGENT_MODEL', 'gpt-4o-mini')
AGENT_BASE_URL = os.environ.get('GZD_AGENT_BASE_URL', '')
