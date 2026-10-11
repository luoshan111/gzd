import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask

from routes.employee_routes import register_employee_routes
from services import employee_service


class EmployeeListTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        self.addCleanup(self.connection.close)
        self.connection.execute(
            'CREATE TABLE employees (real_name TEXT, id_number TEXT, bank_account TEXT, '
            'bank_address TEXT, phone TEXT, sx TEXT, deleted INTEGER)'
        )
        self.connection.executemany(
            'INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?)',
            [
                ('张三', '身份证', '000123456', '测试银行', '13800000001', 'zs', 0),
                ('张四', '', '', '', '13900000002', 'zs', 0),
                ('已删除', '', '', '', '13800000001', 'ysc', 1),
                ("特殊%_\\'姓名", '', '', '', '13700000003', 'tsxm', 0),
            ],
        )

        def paginate(sql, params=(), page=1, page_size=20):
            total = self.connection.execute(
                f'SELECT COUNT(*) FROM ({sql})', params
            ).fetchone()[0]
            rows = self.connection.execute(
                sql + ' LIMIT ? OFFSET ?', params + (page_size, (page - 1) * page_size)
            ).fetchall()
            return dict(data=[dict(row) for row in rows], total=total, page=page,
                        page_size=page_size, pages=max(1, (total + page_size - 1) // page_size))

        patcher = patch.object(employee_service, 'query_paginated', side_effect=paginate)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = Flask(__name__)
        app.secret_key = 'employee-list-test'
        register_employee_routes(app)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['user_id'] = 1

    def test_default_list_preserves_fields_and_excludes_recycled_employees(self):
        result = self.client.get('/api/employees').get_json()
        self.assertTrue(result['success'])
        self.assertEqual(result['total'], 3)
        row = next(row for row in result['data'] if row['real_name'] == '张三')
        self.assertEqual(row['bank_account'], '000123456')
        self.assertEqual(row['id_number'], '身份证')

    def test_name_phone_and_initial_search_with_pagination(self):
        for keyword, total in [('张', 2), ('zs', 2), ('13800000001', 1), ('不存在', 0)]:
            with self.subTest(keyword=keyword):
                result = self.client.get('/api/employees', query_string={
                    'q': keyword, 'page_size': 1
                }).get_json()
                self.assertEqual(result['total'], total)
                self.assertEqual(len(result['data']), min(total, 1))
        second = self.client.get('/api/employees?q=zs&page_size=1&page=2').get_json()
        self.assertEqual(second['page'], 2)
        self.assertEqual(second['pages'], 2)
        self.assertEqual(len(second['data']), 1)

    def test_search_special_characters_are_literal_not_sql_or_like_patterns(self):
        for keyword in ['%', '_', '\\', "'"]:
            with self.subTest(keyword=keyword):
                result = self.client.get('/api/employees', query_string={'q': keyword}).get_json()
                self.assertEqual(result['total'], 1)
                self.assertTrue(result['data'][0]['real_name'].startswith('特殊'))
        self.assertEqual(self.client.get('/api/employees', query_string={
            'q': "' OR 1=1 --"
        }).get_json()['total'], 0)

    def test_filter_trims_spaces_and_retains_login_and_pagination_validation(self):
        self.assertEqual(self.client.get('/api/employees?q=%20zs%20').get_json()['total'], 2)
        self.assertEqual(self.client.get('/api/employees?page=bad').status_code, 400)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get('/api/employees?q=张').status_code, 401)


if __name__ == '__main__':
    unittest.main()
