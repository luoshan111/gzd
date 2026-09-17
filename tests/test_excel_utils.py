import io
import unittest
from unittest.mock import patch

from openpyxl import load_workbook

import excel_utils


class ExcelExportSafetyTests(unittest.TestCase):
    def test_employee_text_is_never_exported_as_a_formula(self):
        employee = {
            'real_name': '=危险姓名',
            'id_number': '=1+1',
            'bank_account': '+123456',
            'bank_address': '=HYPERLINK("bad")',
            'phone': '@危险电话',
        }
        with patch.object(excel_utils, 'query_all', return_value=[employee]):
            buffer, _, _ = excel_utils.build_export_buffer(['=危险姓名'])

        workbook = load_workbook(io.BytesIO(buffer.getvalue()), data_only=False)
        worksheet = workbook['员工信息']
        for cell in worksheet[2]:
            self.assertEqual(cell.data_type, 's')
        self.assertEqual(worksheet['B2'].value, '=1+1')
        self.assertEqual(worksheet['D2'].value, '=HYPERLINK("bad")')
        workbook.close()


if __name__ == '__main__':
    unittest.main()
