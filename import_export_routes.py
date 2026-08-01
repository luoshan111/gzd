"""Excel 导入、导出和文件下载 API。"""

import os

from flask import request, send_file, session

import config
from app_common import ALLOWED_UPLOAD_EXTENSIONS, api_err, api_ok, login_required
from excel_utils import (
    IMPORT_COLUMNS, classify_import_rows, export_employees, import_employee_rows,
    read_employee_excel, read_names, summarize_import_rows,
)
from log_utils import db_log, sys_log


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

    @app.route('/api/export', methods=['POST'])
    @login_required
    def export_excel():
        """读取 input.xlsx 中的姓名列表，匹配数据库信息后导出到 output.xlsx。"""
        try:
            names = read_names(config.INPUT_XLSX)
        except FileNotFoundError as e:
            return api_err(str(e), status=404)

        if not names:
            return api_err('input.xlsx 中没有姓名数据')

        try:
            total, matched = export_employees(names, config.OUTPUT_XLSX)
        except Exception as e:
            sys_log.exception('导出 Excel 失败')
            return api_err('导出失败，请查看系统日志', status=500)

        sys_log.info('用户 %s 批量导出 Excel: 共 %s 条，匹配 %s 条',
                    session.get('username'), total, matched)
        return api_ok('导出成功', file=config.OUTPUT_XLSX, total=total, matched=matched)


    @app.route('/api/export-manual', methods=['POST'])
    @login_required
    def export_manual_excel():
        """接收前端输入的姓名列表，匹配数据库信息后导出到 shuchu.xlsx。"""
        data = request.get_json(silent=True) or {}
        names = [str(n).strip() for n in data.get('names', []) if str(n).strip()]

        if not names:
            return api_err('请提供姓名列表')

        try:
            total, matched = export_employees(names, config.MANUAL_OUTPUT_XLSX)
        except Exception as e:
            sys_log.exception('手动导出 Excel 失败')
            return api_err('导出失败，请查看系统日志', status=500)

        sys_log.info('用户 %s 手动导出 Excel: 共 %s 条，匹配 %s 条',
                    session.get('username'), total, matched)
        return api_ok('导出成功', file=config.MANUAL_OUTPUT_XLSX, total=total, matched=matched)


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


    @app.route('/api/download/<filename>')
    @login_required
    def download_file(filename):
        """
        下载导出的 Excel 文件。
        仅允许下载白名单内的文件（output.xlsx / shuchu.xlsx），防止路径穿越攻击。
        """
        path = config.ALLOWED_DOWNLOADS.get(filename)
        if not path or not os.path.exists(path):
            return api_err('文件不存在或不允许下载', status=404)
        sys_log.info('用户 %s 下载文件: %s', session.get('username'), filename)
        return send_file(path, as_attachment=True)
