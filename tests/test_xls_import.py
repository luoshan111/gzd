"""用真实 BIFF .xls 字节验证标准与智能导入。"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import xlwt
from flask import Flask

from core import config, db
from routes.import_export_routes import register_import_export_routes
from services.excel_utils import read_employee_excel, read_names
from services.legacy_excel import load_legacy_xls
from services.legacy_template import LegacyTemplateError


def xls_bytes(headers, records):
    book = xlwt.Workbook(encoding='utf-8')
    sheet = book.add_sheet('员工信息')
    for row_index, row in enumerate([headers, *records]):
        for column_index, value in enumerate(row):
            if value is not None:
                sheet.write(row_index, column_index, value)
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


class LegacyImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gzd-xls-import-')
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        no_native_excel = patch('services.smart_fill_service.convert_legacy_template',
                                side_effect=AssertionError('Data imports must not start Excel'))
        no_native_excel.start()
        self.addCleanup(no_native_excel.stop)
        database_override = patch.object(config, 'DB_PATH', str(self.folder / 'employees.db'))
        database_override.start()
        self.addCleanup(database_override.stop)
        db.init_db()
        app = Flask(__name__)
        app.secret_key = 'xls-test-key'
        register_import_export_routes(app)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['user_id'] = 1
            session['username'] = 'tester'

    def test_standard_xls_preview_and_confirm_update_database(self):
        source = xls_bytes(
            ['姓名', '身份证号', '银行卡号'],
            [['张三', '110101199001011234', '000123456'],
             ['李四', '110101199201011234', '000987654']],
        )
        response = self.client.post('/api/import-preview', data={
            'file': (io.BytesIO(source), '员工.xls'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200, response.get_json())
        rows = response.get_json()['rows']
        self.assertEqual(rows[0]['status'], 'new')
        self.assertEqual(rows[0]['bank_account'], '000123456')
        confirmed = self.client.post('/api/import-confirm', json={'rows': rows})
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        self.assertEqual(confirmed.get_json()['inserted'], 2)
        self.assertEqual(db.query_one('SELECT bank_account FROM employees WHERE real_name=?',
                                      ('张三',))['bank_account'], '000123456')

    def test_smart_xls_preview_confirm_and_independent_update_control(self):
        db.execute('INSERT INTO employees (real_name, id_number, bank_account) VALUES (?,?,?)',
                   ('张三', '原证件', '原银行卡'))
        source = xls_bytes(
            ['人员', '证件信息', '结算账户'],
            [['张三', '新证件', '000123'], ['李四', '李四证件', '000456']],
        )
        with patch.object(config, 'AGENT_API_KEY', ''):
            preview = self.client.post('/api/smart-import-preview', data={
                'file': (io.BytesIO(source), '员工.xls'),
            }, content_type='multipart/form-data')
        self.assertEqual(preview.status_code, 200, preview.get_json())
        data = preview.get_json()
        self.assertEqual(data['preview']['summary']['new'], 1)
        self.assertEqual(data['preview']['summary']['update'], 1)
        self.assertEqual(data['preview']['tables'][0]['fields'][0]['header'], '人员')
        confirmed = self.client.post('/api/smart-import-confirm', data={
            'preview_token': data['preview_token'],
            'file': (io.BytesIO(source), '员工.xls'),
            'allow_new': '1', 'allow_update': '0', 'allow_restore': '0',
        }, content_type='multipart/form-data')
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        self.assertEqual((confirmed.get_json()['inserted'], confirmed.get_json()['updated']),
                         (1, 0))
        self.assertEqual(db.query_one('SELECT id_number FROM employees WHERE real_name=?',
                                      ('张三',))['id_number'], '原证件')
        self.assertEqual(db.query_one('SELECT bank_account FROM employees WHERE real_name=?',
                                      ('李四',))['bank_account'], '000456')

    def test_xls_formula_and_numeric_identifier_are_rejected(self):
        source = xls_bytes(
            ['姓名', '身份证号', '银行卡号'],
            [['公式人员', xlwt.Formula('1+1'), '000123'],
             ['数值人员', '110101199001011234', 6222021234567890123]],
        )
        rows = read_employee_excel(io.BytesIO(source))
        self.assertTrue(rows[0]['_force_error'])
        self.assertIn('公式', rows[0]['_validation_messages'][0])
        self.assertTrue(rows[1]['_force_error'])
        self.assertIn('数值格式', rows[1]['_validation_messages'][0])
        with patch.object(config, 'AGENT_API_KEY', ''):
            preview = self.client.post('/api/smart-import-preview', data={
                'file': (io.BytesIO(source), '风险.xls'),
            }, content_type='multipart/form-data')
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertEqual(preview.get_json()['preview']['summary']['error'], 2)

    def test_xls_name_list_is_read_without_uploading_to_database(self):
        path = self.folder / 'input.xls'
        path.write_bytes(xls_bytes(['姓名'], [['张三'], ['李四']]))
        self.assertEqual(read_names(str(path)), ['张三', '李四'])

    def test_xls_wage_template_has_clear_fallback_if_native_conversion_unavailable(self):
        source = xls_bytes(['姓名', '身份证号'], [['张三', '旧证件']])
        with patch('services.smart_fill_service.convert_legacy_template',
                   side_effect=LegacyTemplateError('Excel 转换不可用，请另存为 .xlsx')):
            response = self.client.post('/api/smart-fill-preview', data={
                'file': (io.BytesIO(source), '工资表.xls'),
            }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 422)
        self.assertIn('.xlsx', response.get_json()['message'])
        self.assertTrue(response.get_json()['fallback_available'])

    def test_formula_location_is_preserved_across_multiple_xls_sheets(self):
        book = xlwt.Workbook(encoding='utf-8')
        first = book.add_sheet('说明')
        first.write(0, 0, '说明')
        second = book.add_sheet('员工')
        second.write(0, 0, '姓名')
        second.write(0, 1, '身份证号')
        second.write(1, 0, '张三')
        second.write(1, 1, xlwt.Formula('1+1'))
        output = io.BytesIO()
        book.save(output)
        workbook = load_legacy_xls(output.getvalue())
        self.assertEqual(workbook['说明']['A1'].value, '说明')
        self.assertEqual(workbook['员工']['B2'].data_type, 'f')
        workbook.close()


if __name__ == '__main__':
    unittest.main()
