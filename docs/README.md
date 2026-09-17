# 员工信息管理系统

这是一个基于 Flask + SQLite + pandas 的员工信息管理系统，适用于员工档案查询、信息录入、Excel 导入导出与后台用户管理。

## 项目简介

该项目主要提供以下能力：

- 员工信息的新增、编辑、删除与查询
- 软删除与回收站（删除可追溯、可恢复，记录删除时间与操作人）
- 姓名拼音首字母搜索（关键词通配符已转义）
- 员工列表与回收站分页展示（默认每页 20 条，最多 100 条）
- Excel 文件导入预览与导出
- 上传项目工资表模板，智能识别字段并填写数据库员工信息
- 操作日志（管理员）：分"系统日志"与"数据库改动日志"两类落盘到 `logs/`，页面内按类别/日期/级别/关键词查询
- SQLite 数据库手动备份：管理员在后台点击按钮创建，默认保留最近 10 个文件
- 管理员用户管理
- 基于 Session 的登录认证

## 技术栈

- Python 3.x
- Flask
- SQLite
- pandas
- openpyxl
- pypinyin
- Werkzeug

## 项目文件说明

- `app.py`：Flask 应用入口，负责初始化、全局错误处理和路由模块注册
- `app_common.py`：统一 API 响应格式、鉴权装饰器和公共字段工具
- `auth_routes.py`：登录、登出和登录状态接口
- `page_routes.py`：主页、后台、回收站和备份页面路由
- `employee_routes.py`：员工信息与回收站 API
- `import_export_routes.py`：Excel 导入、导出 API
- `admin_routes.py`：日志、备份和管理员用户 API
- `config.py`：集中配置（数据库/文件路径/密钥，支持环境变量覆盖）
- `db.py`：数据库访问层，含建表、旧库迁移与查询助手
- `excel_utils.py`：Excel 导入导出共享逻辑
- `smart_import_service.py`：任意员工表的智能字段识别和选择性导入
- `smart_fill_service.py`：工资表模板智能识别与安全填充
- `log_utils.py`：日志模块，负责日志落盘（按天滚动）与日志查询
- `backup_utils.py`：SQLite 一致性备份、完整性校验与旧备份清理
- `gzb_backup.py`：手动创建数据库备份的命令行工具
- `templates/`：页面模板（主页、登录、管理后台、回收站）
- `logs/`：运行时日志目录（system.log 系统日志 / database.log 数据库改动日志，按天滚动）
- `gzb_admin.py`：后台管理命令行工具，用于创建/删除/重置用户
- `gzb_find.py`：简单命令行查询工具，用于按姓名查询员工信息
- `gzb_update.py`：Excel 导入工具，用于把 Excel 数据写入数据库
- `gzb_output.py`：示例导出脚本，用于生成员工报表
- `data/sjk.db`：SQLite 数据库文件
- `data/input.xlsx`：输入 Excel 文件
- `data/output.xlsx`：命令行脚本 `gzb_output.py` 的输出文件（网页导出不落盘）

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 初始化数据库

项目启动时会自动创建 `users` 和 `employees` 表。

### 3. 启动项目

最简单的方式：直接双击 `scripts/启动项目.bat`（脚本自动定位项目目录、检查 Python 与依赖，项目文件夹移动后无需改任何路径）。关闭服务则双击 `scripts/关闭项目.bat`。

手动方式：

```bash
python app.py
```

端口、调试模式和备份目录等可通过环境变量覆盖，详见 `config.py` 顶部注释（如 `GZD_PORT`、`GZD_DEBUG`、`GZD_BACKUP_DIR`）。

### 4. 数据备份

系统默认不会在启动时自动备份。管理员可在“管理后台”中点击“立即备份”，成功或失败都会弹窗提示；点击“查看备份”可以进入备份子页面查看和下载历史备份。默认备份到 `backups/`，保留最近 10 个备份文件。

也可以手动执行：

```bash
python gzb_backup.py
```

可通过以下环境变量调整：

- `GZD_BACKUP_DIR`：指定备份目录
- `GZD_BACKUP_RETENTION`：保留备份文件数量，默认 10

### 5. 访问地址

打开浏览器访问：

```text
http://127.0.0.1:5001
```

## 默认登录方式

该系统通过登录页验证用户身份。首次使用前请先使用管理员账号创建用户。

### 创建管理员账户示例

```bash
python gzb_admin.py add admin 123456 --admin
```

然后使用上述用户名密码登录系统。

## 界面设计

系统采用统一的现代浅色设计风格：

- 背景色 #f1f5f9，白色圆角卡片布局
- 主色调 #4f46e5（indigo），贯穿所有页面
- 顶部导航栏，标签页切换功能模块
- Toast 通知弹窗（右下角，3 秒自动消失）
- 响应式布局，适配移动端

### 员工列表排序

员工列表和搜索结果默认按姓名（
eal_name）升序排列。

## 主要功能说明

### 员工信息管理

- 新增员工记录
- 更新员工记录
- 删除员工记录（软删除，进回收站）
- 按姓名或拼音首字母查询
- 在职员工列表支持分页浏览，显示当前页、总页数和总记录数

### 回收站

- 查看已删除记录及删除时间、删除人
- 回收站支持分页浏览，默认每页 20 条
- 恢复记录到在职列表
- 管理员可彻底删除（不可恢复）

### Excel 导入

- 网页直接上传 `.xlsx` 文件，自动识别中英文表头
- 先生成校验报告（新增/更新/恢复/错误逐行标注），确认无误后再写入
- 智能导入可识别不同项目的非标准表头，预览字段映射，并分别控制新建、更新和恢复；缺失列或空白值不会清空已有档案
- 也可用 `gzb_update.py` 命令行导入

### Excel 导出

- 通过 `input.xlsx` 中的姓名列表导出，或在前端手动输入姓名列表导出
- 可上传不同项目的 `.xlsx` 工资表模板，先预览确认字段映射，再填写完整空白行；新增行保留并平移模板公式，避开半填写记录和汇总行
- 导出文件在内存中生成、浏览器直接下载（`导出信息_时间戳.xlsx`，保存在浏览器默认下载目录），服务器不落盘，多用户并发导出互不影响
- AI 助手导出文件在内存中短暂保存，下载链接 10 分钟后失效
- 命令行脚本 `gzb_output.py` 仍输出到 `data/output.xlsx`

### 用户与权限

- 普通用户登录后可查询和修改员工信息、使用回收站恢复记录
- 管理员可管理系统用户、彻底删除回收站记录、查看操作日志

## 目录结构

```text
.
├── app.py                  # Flask 应用入口
├── app_common.py           # 统一响应、鉴权装饰器
├── config.py               # 集中配置
├── db.py                   # 数据库访问层
├── admin_routes.py         # 管理员 API
├── auth_routes.py          # 登录登出 API
├── employee_routes.py      # 员工与回收站 API
├── import_export_routes.py # Excel 导入导出 API
├── page_routes.py          # 页面路由
├── excel_utils.py          # Excel 工具
├── smart_fill_service.py   # 工资表模板智能识别与填充
├── log_utils.py            # 日志模块
├── backup_utils.py         # 备份工具
├── gzb_admin.py            # CLI 用户管理
├── gzb_backup.py           # CLI 备份
├── gzb_find.py             # CLI 查询
├── gzb_update.py           # CLI 导入
├── gzb_output.py           # CLI 导出
├── requirements.txt
├── data/                   # 数据文件
│   ├── sjk.db
│   └── input.xlsx
├── templates/              # 页面模板
│   ├── index.html
│   ├── login.html
│   ├── admin.html
│   ├── backup.html
│   ├── recycle_bin.html
│   └── components/
├── docs/                   # 项目文档
│   ├── README.md
│   ├── 使用文档.md
│   └── 开发文档.md
├── scripts/                # 启动/关闭脚本
│   ├── 启动项目.bat
│   └── 关闭项目.bat
├── logs/                   # 运行时日志
└── backups/                # 数据库备份
```

## 开发建议

以下已完成：模板目录拆分、配置环境变量化、统一错误处理与日志、Excel 逻辑抽离、Web 端 Excel 上传导入、操作日志落盘与页面查询、员工列表与回收站分页。

后续可选方向：

- 员工列表排序
- 备份恢复演练与异地备份

## 说明

本项目目前属于内部管理型小工具，适合用于单位/企业内部员工档案处理场景。后续如果有扩展需求，可以继续升级为多角色权限系统、文件上传、导入校验、数据审计等能力。
