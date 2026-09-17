# 数据库备份接口 404 修复 — 交接文档

## 问题
点 [创建备份] 后页面显示 **接口不存在**。

## 根本原因
两个独立页面 `templates/backup.html` 与 `templates/admin.html` 的前端 JS
调用的是 `/api/backups*`,但 `routes/admin_routes.py` 实际注册的是 `/api/admin/backup*`。
因此请求命中 `app.py` 的 404 handler,返回 {"success": false, "message": "接口不存在"}。

旧路径 (前端调用,均不存在):
- GET  /api/backups
- POST /api/backups
- GET  /api/backups/<filename>/download
- DELETE /api/backups/<filename>

实际路由 (`routes/admin_routes.py`):
- POST /api/admin/backup            -> create_backup_api
- GET  /api/admin/backups           -> get_backups
- GET  /api/admin/backup/<path:filename> -> download_backup
- DELETE /api/admin/backup/<path:filename> -> delete_backup_api (已新增)

## 已完成
1. `templates/backup.html` 前端路径全部改为 `/api/admin/backup*`。
2. `templates/admin.html` 前端路径全部改为 `/api/admin/backup*`。
3. `b.size` (字节数) 改为 `b.size_text` (可读大小),列表展示更友好。
4. 下载链接加上 `encodeURIComponent` 防止中文/特殊字符文件名出错。
5. `routes/admin_routes.py` 已新增 DELETE 路由 `/api/admin/backup/<path:filename>`，
   视图函数 `delete_backup_api` 已写好，并调用
   `core.backup_utils.delete_backup`。

## 当前状态

备份删除函数已经存在于 `core/backup_utils.py`，本交接文档中的“未完成”内容是历史记录，已处理完成。

### 无需改动
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
- D:\code\gzd\routes\admin_routes.py  (加 DELETE 路由 + import, 已完成)
- D:\code\gzd\core\backup_utils.py    (包含 delete_backup，已完成)

## 给下一位的提示
PowerShell here-string + python pipe 在这个 shell 里会被吞换行,
导致看似写入成功但实际文件无变化。
写多行 Python 推荐方式: 先 `Set-Content` 把脚本存成 .py,再 `python script.py`;
或者直接在编辑器里贴代码。
