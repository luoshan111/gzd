# 员工信息管理系统

这是一个基于 Flask + SQLite + pandas 的员工信息管理系统，适用于员工档案查询、信息录入、Excel 导入导出与后台用户管理。

## 项目简介

该项目主要提供以下能力：

- 员工信息的新增、编辑、删除与查询
- 姓名拼音首字母搜索
- Excel 文件导入预览与导出
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

- `app.py`：主应用入口，包含 Flask 路由、接口、登录鉴权、Excel 导出逻辑
- `gzb_admin.py`：后台管理命令行工具，用于创建/删除/重置用户
- `gzb_find.py`：简单命令行查询工具，用于按姓名查询员工信息
- `gzb_update.py`：Excel 导入工具，用于把 Excel 数据写入数据库
- `gzb_output.py`：示例导出脚本，用于生成员工报表
- `sjk.db`：SQLite 数据库文件
- `input.xlsx`：输入 Excel 文件
- `output.xlsx`：导出结果文件
- `shuchu.xlsx`：手动导出结果文件

## 快速开始

### 1. 安装依赖

```bash
pip install flask pandas openpyxl pypinyin Werkzeug
```

### 2. 初始化数据库

项目启动时会自动创建 `users` 和 `employees` 表。

### 3. 启动项目

推荐方式：

```bash
python -c "from app import app; app.run(port=5001, debug=True, host='0.0.0.0')"
```

### 4. 访问地址

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

## 主要功能说明

### 员工信息管理

- 新增员工记录
- 更新员工记录
- 删除员工记录
- 按姓名或拼音首字母查询

### Excel 导出

- 通过 `input.xlsx` 中的姓名列表生成结果文件 `output.xlsx`
- 也支持手动输入姓名列表导出到 `shuchu.xlsx`

### 用户与权限

- 普通用户登录后可查询和修改员工信息
- 管理员可管理系统用户

## 目录结构

```text
.
├── app.py
├── gzb_admin.py
├── gzb_find.py
├── gzb_update.py
├── gzb_output.py
├── README.md
├── sjk.db
├── input.xlsx
├── output.xlsx
└── shuchu.xlsx
```

## 开发建议

- 建议后续把前端模板和静态资源拆分到独立目录中
- 建议把 `app.secret_key` 与数据库路径改为环境变量配置
- 建议为 API 增加统一错误处理与日志记录
- 建议将 Excel 导出逻辑抽成独立服务/工具函数

## 说明

本项目目前属于内部管理型小工具，适合用于单位/企业内部员工档案处理场景。后续如果有扩展需求，可以继续升级为多角色权限系统、文件上传、导入校验、数据审计等能力。
