import hashlib
import io
import json
import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask
from openpyxl import Workbook

import excel_utils
import import_export_routes
import smart_fill_service
import smart_import_service


def workbook_bytes(setup):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = '来源表'
    setup(worksheet)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def employee_connection():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.execute('''
        CREATE TABLE employees(
            real_name TEXT PRIMARY KEY,
            id_number TEXT,
            bank_account TEXT,
            bank_address TEXT,
            phone TEXT,
            sx TEXT,
            deleted INTEGER DEFAULT 0,
            deleted_at TIMESTAMP,
            deleted_by TEXT
        )
    ''')
    return connection


class SmartImportServiceTests(unittest.TestCase):
    def test_recognizes_nonstandard_headers_and_classifies_rows(self):
        template = workbook_bytes(lambda ws: (
            ws.append(['员工资料']),
            ws.append(['人员', '证件信息', '结算账户', '收款银行', '联络方式']),
            ws.append(['张三', '110101199001011234', '00123', '测试银行', '13800000000']),
        ))

        with patch.object(smart_fill_service.config, 'AGENT_API_KEY', ''), \
             patch.object(excel_utils, 'query_all', return_value=[]):
            analysis, preview = smart_import_service.prepare_smart_import(template)

        self.assertEqual(analysis['tables'][0]['columns']['real_name'], 'A')
        self.assertEqual(analysis['tables'][0]['columns']['bank_account'], 'C')
        self.assertEqual(preview['rows'][0]['real_name'], '张三')
        self.assertEqual(preview['rows'][0]['bank_account'], '00123')
        self.assertEqual(preview['rows'][0]['status'], 'new')
        self.assertEqual(preview['summary']['new'], 1)

    def test_recognizes_english_and_required_field_headers(self):
        template = workbook_bytes(lambda ws: (
            ws.append(['Employee_Name', 'ID_Number', 'Bank_Account', 'Phone Number']),
            ws.append(['Alice', 'ID-001', '000123', '13800000000']),
        ))

        with patch.object(smart_fill_service.config, 'AGENT_API_KEY', ''), \
             patch.object(excel_utils, 'query_all', return_value=[]):
            analysis, preview = smart_import_service.prepare_smart_import(template)

        columns = analysis['tables'][0]['columns']
        self.assertEqual(columns['real_name'], 'A')
        self.assertEqual(columns['id_number'], 'B')
        self.assertEqual(columns['bank_account'], 'C')
        self.assertEqual(columns['phone'], 'D')
        self.assertEqual(preview['rows'][0]['real_name'], 'Alice')

        self.assertEqual(smart_fill_service._normalize_header('姓名（必填）'), '姓名')
        self.assertEqual(smart_fill_service._normalize_header('身份证号*'), '身份证号')

    def test_update_control_preserves_unmapped_existing_fields(self):
        template = workbook_bytes(lambda ws: (
            ws.append(['姓名', '身份证号']),
            ws.append(['张三', '新身份证']),
            ws.append(['李四', '李四身份证']),
        ))
        with patch.object(smart_fill_service.config, 'AGENT_API_KEY', ''), \
             patch.object(excel_utils, 'query_all', return_value=[]):
            analysis, _ = smart_import_service.prepare_smart_import(template)

        connection = employee_connection()
        connection.execute(
            'INSERT INTO employees '
            '(real_name,id_number,bank_account,bank_address,phone,sx,deleted) '
            'VALUES (?,?,?,?,?,?,0)',
            ('张三', '旧身份证', '原银行卡', '原开户行', '13900000000', 'zs'),
        )
        connection.commit()
        with patch.object(smart_import_service, 'get_connection', return_value=connection):
            update_result = smart_import_service.execute_smart_import(
                template, analysis, {'update'},
            )

        zhang = connection.execute(
            'SELECT * FROM employees WHERE real_name=?', ('张三',)
        ).fetchone()
        self.assertEqual(update_result['updated'], 1)
        self.assertEqual(update_result['inserted'], 0)
        self.assertEqual(zhang['id_number'], '新身份证')
        self.assertEqual(zhang['bank_account'], '原银行卡')
        self.assertEqual(zhang['bank_address'], '原开户行')
        self.assertEqual(zhang['phone'], '13900000000')
        self.assertIsNone(connection.execute(
            'SELECT 1 FROM employees WHERE real_name=?', ('李四',)
        ).fetchone())

        with patch.object(smart_import_service, 'get_connection', return_value=connection):
            new_result = smart_import_service.execute_smart_import(
                template, analysis, {'new'},
            )
        self.assertEqual(new_result['inserted'], 1)
        self.assertEqual(new_result['updated'], 0)
        self.assertIsNotNone(connection.execute(
            'SELECT 1 FROM employees WHERE real_name=?', ('李四',)
        ).fetchone())
        connection.close()

    def test_formula_in_employee_field_is_an_error(self):
        template = workbook_bytes(lambda ws: (
            ws.append(['姓名', '身份证号']),
            ws.append(['张三', '=1+1']),
        ))
        with patch.object(smart_fill_service.config, 'AGENT_API_KEY', ''), \
             patch.object(excel_utils, 'query_all', return_value=[]):
            _, preview = smart_import_service.prepare_smart_import(template)

        self.assertEqual(preview['rows'][0]['status'], 'error')
        self.assertIn('公式', preview['rows'][0]['messages'][0])

    def test_numeric_identifier_cells_are_rejected_as_unsafe(self):
        template = workbook_bytes(lambda ws: (
            ws.append(['姓名', '身份证号', '银行卡号']),
            ws.append(['张三', 110101199001011234, 6222021234567890123]),
        ))
        with patch.object(smart_fill_service.config, 'AGENT_API_KEY', ''), \
             patch.object(excel_utils, 'query_all', return_value=[]):
            _, preview = smart_import_service.prepare_smart_import(template)

        row = preview['rows'][0]
        self.assertEqual(row['status'], 'error')
        self.assertTrue(any('数值格式' in message for message in row['messages']))

    def test_every_duplicate_name_row_is_rejected(self):
        rows = [
            {'_row': 2, 'real_name': '张三', 'id_number': '甲',
             'bank_account': '', 'bank_address': '', 'phone': ''},
            {'_row': 3, 'real_name': '张三', 'id_number': '乙',
             'bank_account': '', 'bank_address': '', 'phone': ''},
        ]

        classified = excel_utils.classify_import_rows(rows, existing={})

        self.assertEqual([row['status'] for row in classified], ['error', 'error'])
        self.assertTrue(all('文件中姓名重复' in row['messages'] for row in classified))

    def test_restore_runs_only_when_restore_is_allowed(self):
        template = workbook_bytes(lambda ws: (
            ws.append(['姓名', '身份证号']),
            ws.append(['王五', '新身份证']),
        ))
        with patch.object(smart_fill_service.config, 'AGENT_API_KEY', ''), \
             patch.object(excel_utils, 'query_all', return_value=[]):
            analysis, _ = smart_import_service.prepare_smart_import(template)

        connection = employee_connection()
        connection.execute(
            'INSERT INTO employees '
            '(real_name,id_number,bank_account,bank_address,phone,sx,deleted,deleted_at,deleted_by) '
            'VALUES (?,?,?,?,?,?,1,?,?)',
            ('王五', '旧身份证', '原银行卡', '原开户行', '13700000000', 'ww',
             '2026-01-01', 'admin'),
        )
        connection.commit()
        with patch.object(smart_import_service, 'get_connection', return_value=connection):
            with self.assertRaisesRegex(smart_import_service.TemplateFillError, '没有可导入'):
                smart_import_service.execute_smart_import(template, analysis, {'update'})
        with patch.object(smart_import_service, 'get_connection', return_value=connection):
            result = smart_import_service.execute_smart_import(
                template, analysis, {'restore'},
            )

        restored = connection.execute(
            'SELECT * FROM employees WHERE real_name=?', ('王五',)
        ).fetchone()
        self.assertEqual(result['restored'], 1)
        self.assertEqual(restored['deleted'], 0)
        self.assertEqual(restored['id_number'], '新身份证')
        self.assertEqual(restored['bank_account'], '原银行卡')
        self.assertIsNone(restored['deleted_at'])
        self.assertIsNone(restored['deleted_by'])
        connection.close()


class SmartImportRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'test-secret'
        import_export_routes.register_import_export_routes(self.app)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['user_id'] = 1
            session['username'] = 'tester'
        import_export_routes._smart_import_preview_store.clear()

    def test_preview_and_confirm_pass_separate_operation_controls(self):
        analysis = {'confidence': 0.9, 'tables': []}
        preview = {
            'confidence': 0.9,
            'tables': [],
            'rows': [{'real_name': '张三', 'status': 'new'}],
            'summary': {'total': 1, 'new': 1, 'update': 0, 'restore': 0, 'error': 0},
            'notes': [],
        }
        result = {
            'inserted': 1, 'updated': 0, 'restored': 0, 'excluded': 0,
            'errors': 0, 'selected': 1, 'summary': preview['summary'],
        }
        with patch.object(import_export_routes, 'prepare_smart_import',
                          return_value=(analysis, preview)):
            preview_response = self.client.post('/api/smart-import-preview', data={
                'file': (io.BytesIO(b'client-file'), '员工表.xlsx'),
            }, content_type='multipart/form-data')

        self.assertEqual(preview_response.status_code, 200)
        token = preview_response.get_json()['preview_token']
        stored = import_export_routes._smart_import_preview_store[token]
        self.assertEqual(
            stored['template_digest'], hashlib.sha256(b'client-file').hexdigest(),
        )
        self.assertNotIn('template_bytes', stored)

        with patch.object(import_export_routes, 'execute_smart_import',
                          return_value=result) as execute_mock:
            confirm_response = self.client.post('/api/smart-import-confirm', data={
                'preview_token': token,
                'file': (io.BytesIO(b'client-file'), '员工表.xlsx'),
                'allow_new': '1',
                'allow_update': '0',
                'allow_restore': '0',
            }, content_type='multipart/form-data')

        self.assertEqual(confirm_response.status_code, 200)
        execute_mock.assert_called_once_with(b'client-file', analysis, {'new'})

    def test_confirm_rejects_a_changed_client_file(self):
        token = import_export_routes._store_smart_import_preview(
            1, hashlib.sha256(b'previewed').hexdigest(), {'confidence': 0.9},
        )
        with patch.object(import_export_routes, 'execute_smart_import') as execute_mock:
            response = self.client.post('/api/smart-import-confirm', data={
                'preview_token': token,
                'file': (io.BytesIO(b'changed'), '员工表.xlsx'),
                'allow_new': '1',
            }, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 409)
        execute_mock.assert_not_called()

    def test_preview_token_is_bound_to_current_user(self):
        token = import_export_routes._store_smart_import_preview(
            2, hashlib.sha256(b'client-file').hexdigest(), {'confidence': 0.9},
        )

        with patch.object(import_export_routes, 'execute_smart_import') as execute_mock:
            response = self.client.post('/api/smart-import-confirm', data={
                'preview_token': token,
                'file': (io.BytesIO(b'client-file'), '员工表.xlsx'),
                'allow_new': '1',
            }, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 404)
        execute_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
