"""Excel 导入、导出 API。"""

import os
from datetime import datetime

from flask import request, send_file, session

import config
from app_common import ALLOWED_UPLOAD_EXTENSIONS, api_err, api_ok, login_required
from excel_utils import (
    IMPORT_COLUMNS, classify_import_rows, build_export_buffer, import_employee_rows,
    read_employee_excel, read_names, summarize_import_rows,
)
from log_utils import db_log, sys_log

# 导出 Excel 的 MIME 类型
EXPORT_MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def register_import_export_routes(app):
    # ==================== Excel 上传导入 API ====================

    @app.route('/api/import-preview', methods=['POST'])
    @login_required
    def import_preview():
        """
        上传 Excel 并返回校验预览报告（只解析不写库）。
        multipart 字段: file（.xlsx，最大 5MB，内存中解析不落盘）
        返回: rows（每行含数据、status、messages）+ summary（分类统计）
        """
        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请选择要上传的 Excel 文件')

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            return api_err('仅支持 .xlsx 格式文件')

        try:
            rows = read_employee_excel(file.stream)
        except ValueError as e:
            return api_err(str(e), status=400)
        except Exception as e:
            sys_log.warning('导入预览解析失败: %s', e)
            return api_err('文件解析失败，请确认是有效的 .xlsx 文件')

        if not rows:
            return api_err('文件中没有数据行')

        rows = classify_import_rows(rows)
        return api_ok(rows=rows, summary=summarize_import_rows(rows))


    @app.route('/api/import-confirm', methods=['POST'])
    @login_required
    def import_confirm():
        """
        确认导入：接收预览通过的行数据，服务端重新清洗校验后单事务写入。
        JSON: {"rows": [{real_name, id_number, bank_account, bank_address, phone}, ...]}
        说明: 不信任前端传入的 status，一切以服务端重新分类为准。
        """
        data = request.get_json(silent=True) or {}
        raw_rows = data.get('rows', [])
        if not raw_rows:
            return api_err('没有可导入的数据')

        # 服务端复核：重新清洗字段并分类（验证 + 打标）
        cleaned = []
        for raw in raw_rows:
            row = {'_row': raw.get('_row', 0)}
            for field in IMPORT_COLUMNS:
                row[field] = str(raw.get(field, '') or '').strip()
            cleaned.append(row)

        rows = classify_import_rows(cleaned)
        result = import_employee_rows(rows)

        db_log.info('用户 %s 导入员工: %s', session.get('username'), result)
        return api_ok('导入完成', **result)


    # ==================== Excel 导出 API ====================

    def _send_export(names: list, username: str, action: str):
        """
        按姓名列表生成导出 Excel 并作为附件直接返回。
        全程在内存中完成，不写共享文件，多个用户并发导出互不影响。
        """
        try:
            buf, total, matched = build_export_buffer(names)
        except Exception:
            sys_log.exception('%s失败', action)
            return api_err('导出失败，请查看系统日志', status=500)

        sys_log.info('用户 %s %s: 共 %s 条，匹配 %s 条', username, action, total, matched)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return send_file(
            buf, as_attachment=True, download_name=f'导出信息_{stamp}.xlsx',
            mimetype=EXPORT_MIMETYPE,
        )

    @app.route('/api/export', methods=['POST'])
    @login_required
    def export_excel():
        """读取 input.xlsx 中的姓名列表，匹配数据库信息后直接返回 Excel 文件流。"""
        try:
            names = read_names(config.INPUT_XLSX)
        except FileNotFoundError as e:
            return api_err(str(e), status=404)

        if not names:
            return api_err('input.xlsx 中没有姓名数据')

        return _send_export(names, session.get('username'), '批量导出 Excel')


    @app.route('/api/export-manual', methods=['POST'])
    @login_required
    def export_manual_excel():
        """接收前端输入的姓名列表，匹配数据库信息后直接返回 Excel 文件流。"""
        data = request.get_json(silent=True) or {}
        names = [str(n).strip() for n in data.get('names', []) if str(n).strip()]

        if not names:
            return api_err('请提供姓名列表')

        return _send_export(names, session.get('username'), '手动导出 Excel')


    @app.route('/api/input-preview')
    @login_required
    def input_preview():
        """预览 input.xlsx 前 20 行姓名，用于前端展示。"""
        try:
            names = read_names(config.INPUT_XLSX, limit=20)
        except FileNotFoundError as e:
            return api_err(str(e), status=404)
        except Exception as e:
            sys_log.exception('读取 input.xlsx 失败')
            return api_err('读取 input.xlsx 失败，请查看系统日志', status=500)

        return api_ok(data=[{'姓名': n} for n in names], columns=['姓名'])
