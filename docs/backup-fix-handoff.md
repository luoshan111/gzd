# 数据库备份接口 404 修复 — 交接文档

## 问题
点 [创建备份] 后页面显示 **接口不存在**。

## 根本原因
两个独立页面 `templates/backup.html` 与 `templates/admin.html` 的前端 JS
调用的是 `/api/backups*`,但 `admin_routes.py` 实际注册的是 `/api/admin/backup*`。
因此请求命中 `app.py` 的 404 handler,返回 {"success": false, "message": "接口不存在"}。

旧路径 (前端调用,均不存在):
- GET  /api/backups
- POST /api/backups
- GET  /api/backups/<filename>/download
- DELETE /api/backups/<filename>

实际路由 (admin_routes.py):
- POST /api/admin/backup            -> create_backup_api
- GET  /api/admin/backups           -> get_backups
- GET  /api/admin/backup/<path:filename> -> download_backup
- DELETE /api/admin/backup/<path:filename> -> delete_backup_api (已新增)

## 已完成
1. `templates/backup.html` 前端路径全部改为 `/api/admin/backup*`。
2. `templates/admin.html` 前端路径全部改为 `/api/admin/backup*`。
3. `b.size` (字节数) 改为 `b.size_text` (可读大小),列表展示更友好。
4. 下载链接加上 `encodeURIComponent` 防止中文/特殊字符文件名出错。
5. `admin_routes.py` 已新增 DELETE 路由 `/api/admin/backup/<path:filename`,
   视图函数 `delete_backup_api` 已写好,import 已改为
   `from backup_utils import create_backup, delete_backup, get_backup_path, list_backups`。

## 未完成 (需下一位处理)

### 1. 给 backup_utils.py 加 delete_backup 函数
文件: D:\code\gzd\backup_utils.py

**重要**: 当前文件里 **没有** `delete_backup` 函数。如果直接启动服务,
会在 `from backup_utils import ... delete_backup` 这一行抛 ImportError,
**所有 API 都会 500**。

请把这段插在 `def _format_size(size: int):` 的正上方:

```python
def delete_backup(filename: str) -> bool:
    """删除指定备份文件,成功返回 True。复用 get_backup_path 的安全校验。"""
    backup_path = get_backup_path(filename)
    if not backup_path:
        return False
    try:
        backup_path.unlink()
        backup_log.info('管理员删除数据库备份: %s', backup_path.name)
        return True
    except OSError:
        backup_log.exception('删除数据库备份失败: %s', backup_path)
        return False
```

### 2. (无需改动)
`download_backup` 已经使用 `send_file(... as_attachment=True, download_name=...)`,
下载链接改路径后能直接生效。

## 验证步骤
1. 完成上面 #1 后,启动服务: `python D:\code\gzd\app.py`
2. 管理员账号登录,访问 `/backup` 或 `/admin`。
3. 点 [创建备份] -> 应出现 toast 备份成功,列表里出现一行。
4. 列表里点 [删除] -> 弹确认框,确认后该行消失。
5. 点 [下载] -> 浏览器下载 .db 文件。

## 改动文件清单
- D:\code\gzd\templates\backup.html   (前端路径修复, 已完成)
- D:\code\gzd\templates\admin.html    (前端路径修复, 已完成)
- D:\code\gzd\admin_routes.py         (加 DELETE 路由 + import, 已完成)
- D:\code\gzd\backup_utils.py         (加 delete_backup 函数, **未完成**)

## 给下一位的提示
PowerShell here-string + python pipe 在这个 shell 里会被吞换行,
导致看似写入成功但实际文件无变化。
写多行 Python 推荐方式: 先 `Set-Content` 把脚本存成 .py,再 `python script.py`;
或者直接在编辑器里贴代码。
