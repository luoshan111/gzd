# -*- coding: utf-8 -*-
"""
修改密码功能集成测试（Flask test client，不启动服务器）。

用法：
    python scripts/test_change_password.py

说明：
    - 通过环境变量 GZD_DB_PATH 指向临时数据库，不触碰 data/sjk.db；
    - 覆盖场景：未登录拦截、旧密码校验、新密码规则、正常修改、
      修改后新旧密码登录验证、登录期间用户被删除的边界情况。
    - 全部通过退出码为 0，任一失败为 1。
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')

# 让脚本能找到项目根目录下的 app/db 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 必须在导入 app 前设置，让 init_db 建表到临时库
tmpdir = tempfile.mkdtemp()
os.environ['GZD_DB_PATH'] = os.path.join(tmpdir, 'test.db')

from werkzeug.security import generate_password_hash

import app as app_module
from db import execute, now_local

# 准备一个已知密码的测试用户
execute(
    "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 0, ?)",
    ('tester', generate_password_hash('old123'), now_local())
)

client = app_module.app.test_client()
app_module.app.config['TESTING'] = True
results = []


def check(name, cond, detail=''):
    """记录并打印单项断言结果。"""
    results.append((name, bool(cond)))
    print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + detail) if detail and not cond else '')


def change_password(old, new):
    """以当前登录态调用修改密码接口，返回响应 JSON。"""
    r = client.post('/api/change-password', json={'old_password': old, 'new_password': new})
    return r.get_json()


def login(password):
    """用测试账号登录，返回响应 JSON。"""
    r = client.post('/api/login', json={'username': 'tester', 'password': password})
    return r.get_json()


# ---------- 一、权限拦截：未登录时接口与页面都不可用 ----------
r = client.post('/api/change-password', json={'old_password': 'old123', 'new_password': 'new456'})
check('未登录调用接口返回401', r.status_code == 401 and not r.get_json()['success'])

r = client.get('/change-password')
check('未登录访问页面跳转登录', r.status_code == 302 and '/login' in r.headers.get('Location', ''))

# ---------- 二、登录后页面可访问 ----------
check('旧密码登录成功', login('old123')['success'])
r = client.get('/change-password')
check('登录后页面可访问', r.status_code == 200 and '修改密码'.encode() in r.data)

# ---------- 三、参数与旧密码校验 ----------
check('旧密码错误被拒绝', not change_password('wrong!', 'new456')['success'])
check('新密码不足4位被拒绝', not change_password('old123', 'abc')['success'])
check('缺少新密码被拒绝', not change_password('old123', None)['success'])

# ---------- 四、正常修改与生效验证 ----------
check('正常修改成功', change_password('old123', 'new456')['success'])

client.post('/api/logout')
check('修改后旧密码登录失败', not login('old123')['success'])
check('修改后新密码登录成功', login('new456')['success'])

# ---------- 五、边界：登录期间用户被管理员删除（session 仍有效） ----------
execute("DELETE FROM users WHERE username = 'tester'")
r = client.post('/api/change-password', json={'old_password': 'new456', 'new_password': 'another9'})
check('用户被删后修改密码返回404', r.status_code == 404 and not r.get_json()['success'])

# ---------- 汇总 ----------
failed = [name for name, ok in results if not ok]
print()
print('总计 %d 项, 失败 %d 项' % (len(results), len(failed)))
sys.exit(1 if failed else 0)
