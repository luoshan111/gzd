"""智能识别员工 Excel，并在本地完成预览、分类和安全导入。"""

from openpyxl.cell.cell import MergedCell

from db import get_connection, get_pinyin_sx
from excel_utils import IMPORT_COLUMNS, _clean_cell, classify_import_rows, summarize_import_rows
from smart_fill_service import (
    FIELD_LABELS, MAX_FILL_ROWS, TemplateFillError,
    _load_template_workbook, _row_contains_summary_marker, _validate_analysis,
    prepare_template,
)


def _mapping_preview(analysis: dict) -> list:
    tables = []
    for table in analysis['tables']:
        fields = []
        for field, column in table['columns'].items():
            header = table['target_headers'][field]
            fields.append({
                'field': field,
                'label': FIELD_LABELS[field],
                'column': column,
                'header': header['text'],
                'header_row': header['row'],
            })
        tables.append({
            'sheet': table['sheet'],
            'header_row': table['header_row'],
            'data_start_row': table['data_start_row'],
            'data_end_row': table['data_end_row'],
            'fields': fields,
        })
    return tables


def extract_smart_import_rows(template_bytes: bytes, analysis: dict) -> tuple:
    """使用已验证映射从客户端文件本地提取员工字段，不调用模型。"""
    workbook = _load_template_workbook(template_bytes, data_only=False)
    try:
        analysis = _validate_analysis(workbook, analysis)
        rows = []
        seen_sources = set()
        for table in analysis['tables']:
            worksheet = workbook[table['sheet']]
            start = table['data_start_row']
            end = table['data_end_row'] or min(
                worksheet.max_row, start + MAX_FILL_ROWS - 1,
            )
            for row_number in range(start, end + 1):
                source_key = (table['sheet'], row_number)
                if source_key in seen_sources:
                    continue
                if _row_contains_summary_marker(worksheet, row_number):
                    break
                row = {
                    '_sheet': table['sheet'],
                    '_row': row_number,
                    '_mapped_fields': sorted(table['columns']),
                }
                formula_fields = []
                unsafe_numeric_fields = []
                validation_messages = []
                for field in IMPORT_COLUMNS:
                    column = table['columns'].get(field)
                    if not column:
                        row[field] = ''
                        continue
                    cell = worksheet[f'{column}{row_number}']
                    if isinstance(cell, MergedCell):
                        row[field] = ''
                    elif cell.data_type == 'f':
                        row[field] = ''
                        formula_fields.append(FIELD_LABELS[field])
                    else:
                        row[field] = _clean_cell(cell.value)
                        if isinstance(cell.value, (int, float)):
                            if field in {'id_number', 'bank_account'}:
                                unsafe_numeric_fields.append(FIELD_LABELS[field])
                            elif field == 'phone':
                                validation_messages.append(
                                    '电话以数值格式存储，前导零可能已经丢失'
                                )
                if not any(row[field] for field in IMPORT_COLUMNS) and not formula_fields:
                    continue
                if formula_fields:
                    row['_force_error'] = True
                    validation_messages.append(
                        '以下员工字段是公式，不能自动导入：' + '、'.join(formula_fields)
                    )
                if unsafe_numeric_fields:
                    row['_force_error'] = True
                    validation_messages.append(
                        '以下标识字段以数值格式存储，可能已丢失精度或前导零，请改为文本：'
                        + '、'.join(unsafe_numeric_fields)
                    )
                if validation_messages:
                    row['_validation_messages'] = validation_messages
                rows.append(row)
                seen_sources.add(source_key)
                if len(rows) > MAX_FILL_ROWS:
                    raise TemplateFillError(
                        f'智能导入一次最多支持 {MAX_FILL_ROWS} 条有效数据行'
                    )
        if not rows:
            raise TemplateFillError('已识别字段映射，但没有找到可导入的数据行')
        return rows, analysis
    finally:
        workbook.close()


def prepare_smart_import(template_bytes: bytes) -> tuple:
    """识别映射、提取数据并按数据库现状生成只读预览。"""
    analysis, mapping = prepare_template(template_bytes)
    rows, analysis = extract_smart_import_rows(template_bytes, analysis)
    rows = classify_import_rows(rows)
    return analysis, {
        'confidence': analysis['confidence'],
        'tables': _mapping_preview(analysis),
        'rows': rows,
        'summary': summarize_import_rows(rows),
        'notes': mapping.get('notes', []),
    }


def execute_smart_import(template_bytes: bytes, analysis: dict, allowed_statuses: set) -> dict:
    """重新解析同一客户端文件，并按确认时的数据库状态执行所选操作。"""
    allowed_statuses = set(allowed_statuses) & {'new', 'update', 'restore'}
    if not allowed_statuses:
        raise TemplateFillError('请至少选择一种导入操作')

    rows, _ = extract_smart_import_rows(template_bytes, analysis)
    with get_connection() as connection:
        connection.execute('BEGIN IMMEDIATE')
        current_rows = connection.execute(
            'SELECT real_name, id_number, bank_account, bank_address, phone, deleted '
            'FROM employees'
        ).fetchall()
        existing = {row['real_name']: row for row in current_rows}
        classified = classify_import_rows(
            rows, existing={name: row['deleted'] for name, row in existing.items()},
        )
        selected = [row for row in classified if row['status'] in allowed_statuses]
        if not selected:
            raise TemplateFillError('当前所选范围没有可导入的数据')

        inserted = updated = restored = 0
        for row in selected:
            name = row['real_name']
            status = row['status']
            if status == 'new':
                connection.execute(
                    'INSERT INTO employees '
                    '(real_name, id_number, bank_account, bank_address, phone, sx) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (name, row['id_number'], row['bank_account'], row['bank_address'],
                     row['phone'], get_pinyin_sx(name)),
                )
                inserted += 1
                existing[name] = {
                    'real_name': name, 'id_number': row['id_number'],
                    'bank_account': row['bank_account'], 'bank_address': row['bank_address'],
                    'phone': row['phone'], 'deleted': 0,
                }
                continue

            old = existing[name]
            mapped = set(row.get('_mapped_fields') or [])
            values = {}
            for field in IMPORT_COLUMNS[1:]:
                incoming = row[field]
                values[field] = incoming if field in mapped and incoming else (old[field] or '')
            connection.execute(
                'UPDATE employees SET id_number=?, bank_account=?, bank_address=?, phone=?, '
                'sx=?, deleted=0, deleted_at=NULL, deleted_by=NULL WHERE real_name=?',
                (values['id_number'], values['bank_account'], values['bank_address'],
                 values['phone'], get_pinyin_sx(name), name),
            )
            if status == 'restore':
                restored += 1
            else:
                updated += 1
        connection.commit()

    summary = summarize_import_rows(classified)
    return {
        'inserted': inserted,
        'updated': updated,
        'restored': restored,
        'excluded': summary['total'] - len(selected),
        'errors': summary['error'],
        'selected': len(selected),
        'summary': summary,
    }
