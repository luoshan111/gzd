"""Excel HTTP 路由：只负责上传参数和文件响应。"""

import io

from core import config
from flask import request, send_file, session

from core.app_common import api_err, api_ok, login_required
from core.log_utils import sys_log
from services.import_export_service import (
    EXPORT_MIMETYPE, PREVIEW_TTL_SECONDS, confirm_import,
    confirm_smart_fill, confirm_smart_import, export_names, input_preview,
    parse_names, preview_import, preview_smart_fill, preview_smart_import,
    validate_xlsx_filename, _smart_fill_preview_store, _smart_import_preview_store,
    store_smart_fill_preview, store_smart_import_preview,
)
from services.smart_fill_service import (
    MAX_FILL_ROWS, TemplateAnalysisError, TemplateFillError, fill_template,
    prepare_template,
)
from services.smart_import_service import execute_smart_import, prepare_smart_import


# 这些名称保留为服务层迁移期间的兼容注入点；真实业务实现仍在 services/ 中。
def _store_smart_fill_preview(user_id, template_digest, names, analysis):
    return store_smart_fill_preview(user_id, template_digest, names, analysis)


def _store_smart_import_preview(user_id, template_digest, analysis):
    return store_smart_import_preview(user_id, template_digest, analysis)


def register_import_export_routes(app):
    @app.route('/api/import-preview', methods=['POST'])
    @login_required
    def import_preview_api():
        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请选择要上传的 Excel 文件')
        if not validate_xlsx_filename(file.filename):
            return api_err('仅支持 .xls 或 .xlsx 格式文件')
        try:
            rows, summary = preview_import(file.stream)
        except ValueError as exc:
            return api_err(str(exc))
        except Exception as exc:
            sys_log.warning('导入预览解析失败: %s', exc)
            return api_err('文件解析失败，请确认是有效的 .xls 或 .xlsx 文件')
        return api_ok(rows=rows, summary=summary)

    @app.route('/api/import-confirm', methods=['POST'])
    @login_required
    def import_confirm_api():
        data = request.get_json(silent=True) or {}
        raw_rows = data.get('rows', [])
        if not raw_rows:
            return api_err('没有可导入的数据')
        return api_ok('导入完成', **confirm_import(raw_rows, session.get('username')))

    @app.route('/api/smart-import-preview', methods=['POST'])
    @login_required
    def smart_import_preview_api():
        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请选择要智能导入的 Excel 文件')
        if not validate_xlsx_filename(file.filename):
            return api_err('智能导入仅支持 .xls 或 .xlsx 格式文件')
        try:
            template_bytes = file.read()
            token, preview = preview_smart_import(
                template_bytes, session.get('user_id'), prepare_fn=prepare_smart_import,
            )
        except (TemplateAnalysisError, TemplateFillError) as exc:
            sys_log.warning('用户 %s 智能导入预览未完成: %s', session.get('username'), exc)
            return api_err(str(exc), status=422)
        except Exception:
            sys_log.exception('用户 %s 智能导入预览失败', session.get('username'))
            return api_err('智能导入预览失败，请查看系统日志；标准导入仍可继续使用', status=500)
        return api_ok(
            '智能识别完成，请核对字段映射、数据和导入范围',
            preview_token=token, expires_in=PREVIEW_TTL_SECONDS, preview=preview,
        )

    @app.route('/api/smart-import-confirm', methods=['POST'])
    @login_required
    def smart_import_confirm_api():
        token = str(request.form.get('preview_token') or '').strip()
        if not token:
            return api_err('缺少智能导入预览凭证')
        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请重新提交已预览的 Excel 文件')
        if not validate_xlsx_filename(file.filename):
            return api_err('智能导入仅支持 .xls 或 .xlsx 格式文件')
        allowed_statuses = {
            status for status, key in (
                ('new', 'allow_new'), ('update', 'allow_update'), ('restore', 'allow_restore')
            ) if str(request.form.get(key, '')).lower() in {'1', 'true', 'on', 'yes'}
        }
        try:
            result = confirm_smart_import(
                token, session.get('user_id'), file.read(), allowed_statuses,
                session.get('username'), execute_fn=execute_smart_import,
            )
        except LookupError as exc:
            return api_err(str(exc), status=404)
        except ValueError as exc:
            return api_err(str(exc), status=409)
        except (TemplateAnalysisError, TemplateFillError) as exc:
            return api_err(str(exc), status=422)
        except Exception:
            sys_log.exception('用户 %s 智能导入确认失败', session.get('username'))
            return api_err('智能导入失败，请查看系统日志；标准导入仍可继续使用', status=500)
        return api_ok('智能导入完成', **result)

    @app.route('/api/export', methods=['POST'])
    @login_required
    def export_excel():
        try:
            names = read_names(config.INPUT_XLSX)
        except FileNotFoundError as exc:
            return api_err(str(exc), status=404)
        if not names:
            return api_err('input.xlsx 中没有姓名数据')
        try:
            buf, filename = export_names(names, '批量导出 Excel', session.get('username'))
        except Exception:
            sys_log.exception('批量导出 Excel 失败')
            return api_err('导出失败，请查看系统日志', status=500)
        return send_file(buf, as_attachment=True, download_name=filename, mimetype=EXPORT_MIMETYPE)

    @app.route('/api/export-manual', methods=['POST'])
    @login_required
    def export_manual_excel():
        data = request.get_json(silent=True) or {}
        names = [str(n).strip() for n in data.get('names', []) if str(n).strip()]
        if not names:
            return api_err('请提供姓名列表')
        try:
            buf, filename = export_names(names, '手动导出 Excel', session.get('username'))
        except Exception:
            sys_log.exception('手动导出 Excel 失败')
            return api_err('导出失败，请查看系统日志', status=500)
        return send_file(buf, as_attachment=True, download_name=filename, mimetype=EXPORT_MIMETYPE)

    @app.route('/api/smart-fill', methods=['POST'])
    @login_required
    def smart_fill_requires_preview():
        return api_err('智能填表需要先预览并确认字段映射', status=409)

    @app.route('/api/smart-fill-preview', methods=['POST'])
    @login_required
    def smart_fill_preview_api():
        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请选择要填写的 Excel 模板')
        if not validate_xlsx_filename(file.filename):
            return api_err('智能填表支持 .xls 或 .xlsx 格式文件')
        try:
            names = parse_names(request.form.get('names', ''))
        except ValueError as exc:
            return api_err(str(exc))
        try:
            overwrite = str(request.form.get('overwrite', '')).lower() in {'1', 'true', 'on', 'yes'}
            token, preview = preview_smart_fill(
                file.read(), names, session.get('user_id'), prepare_fn=prepare_template,
                overwrite=overwrite,
            )
        except (TemplateAnalysisError, TemplateFillError) as exc:
            return api_err(str(exc), status=422, fallback_available=True)
        except Exception:
            sys_log.exception('用户 %s 智能填表预览失败', session.get('username'))
            return api_err('智能填表预览失败，请查看系统日志；现有手动导出仍可使用',
                           status=500, fallback_available=True)
        return api_ok(
            '模板识别完成，请核对字段映射后确认填写',
            preview_token=token, expires_in=PREVIEW_TTL_SECONDS, preview=preview,
            name_mode='provided' if names else 'template', requested_names=len(names),
            overwrite=overwrite,
        )

    @app.route('/api/smart-fill-confirm', methods=['POST'])
    @login_required
    def smart_fill_confirm_api():
        token = str(request.form.get('preview_token') or '').strip()
        if not token:
            return api_err('缺少智能填表预览凭证')
        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请重新提交已预览的 Excel 模板')
        if not validate_xlsx_filename(file.filename):
            return api_err('智能填表支持 .xls 或 .xlsx 格式文件')
        try:
            output, summary, analysis, filename = confirm_smart_fill(
                token, session.get('user_id'), file.read(), file.filename,
                session.get('username'), fill_fn=fill_template,
            )
        except LookupError as exc:
            return api_err(str(exc), status=404)
        except (TemplateAnalysisError, TemplateFillError) as exc:
            return api_err(str(exc), status=422, fallback_available=True)
        except ValueError as exc:
            return api_err(str(exc), status=409)
        except Exception:
            sys_log.exception('用户 %s 确认智能填表失败', session.get('username'))
            return api_err('智能填表失败，请查看系统日志；现有手动导出仍可使用',
                           status=500, fallback_available=True)
        response = send_file(
            io.BytesIO(output), as_attachment=True, download_name=filename,
            mimetype=EXPORT_MIMETYPE,
        )
        response.headers['X-Smart-Fill-Matched'] = str(summary['matched'])
        response.headers['X-Smart-Fill-Missing'] = str(len(summary['missing']))
        response.headers['X-Smart-Fill-Cells'] = str(summary['cells_filled'])
        response.headers['X-Smart-Fill-Overwritten'] = str(summary.get('overwritten_cells', 0))
        response.headers['X-Smart-Fill-Cleared'] = str(summary.get('cleared_cells', 0))
        response.headers['X-Smart-Fill-Confidence'] = f"{analysis['confidence']:.2f}"
        return response

    @app.route('/api/input-preview')
    @login_required
    def input_preview_api():
        try:
            names = input_preview()
        except FileNotFoundError as exc:
            return api_err(str(exc), status=404)
        except Exception:
            sys_log.exception('读取 input.xlsx 失败')
            return api_err('读取 input.xlsx 失败，请查看系统日志', status=500)
        return api_ok(data=names, columns=['姓名'])
