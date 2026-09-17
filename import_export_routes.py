"""Excel 导入、导出与智能模板填充 API。"""

import hashlib
import io
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime

from flask import request, send_file, session

import config
from app_common import ALLOWED_UPLOAD_EXTENSIONS, api_err, api_ok, login_required
from excel_utils import (
    IMPORT_COLUMNS, classify_import_rows, build_export_buffer, import_employee_rows,
    read_employee_excel, read_names, summarize_import_rows,
)
from log_utils import db_log, sys_log
from smart_import_service import execute_smart_import, prepare_smart_import
from smart_fill_service import (
    MAX_FILL_ROWS, TemplateAnalysisError, TemplateFillError, fill_template, prepare_template,
)

# 导出 Excel 的 MIME 类型
EXPORT_MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
SMART_FILL_PREVIEW_TTL_SECONDS = 10 * 60
SMART_FILL_PREVIEW_MAX_ENTRIES = 20
_smart_fill_preview_store = {}
_smart_fill_preview_lock = threading.Lock()
_smart_import_preview_store = {}
_smart_import_preview_lock = threading.Lock()


def _store_smart_fill_preview(user_id, template_digest, names, analysis) -> str:
    now = time.time()
    with _smart_fill_preview_lock:
        expired = [
            token for token, item in _smart_fill_preview_store.items()
            if now - item['created'] > SMART_FILL_PREVIEW_TTL_SECONDS
        ]
        for token in expired:
            del _smart_fill_preview_store[token]
        while len(_smart_fill_preview_store) >= SMART_FILL_PREVIEW_MAX_ENTRIES:
            oldest = min(_smart_fill_preview_store,
                         key=lambda token: _smart_fill_preview_store[token]['created'])
            del _smart_fill_preview_store[oldest]
        token = uuid.uuid4().hex
        _smart_fill_preview_store[token] = {
            'user_id': user_id,
            'template_digest': template_digest,
            'names': names,
            'analysis': analysis,
            'created': now,
        }
    return token


def _get_smart_fill_preview(token: str, user_id):
    now = time.time()
    with _smart_fill_preview_lock:
        item = _smart_fill_preview_store.get(token)
        if not item or item['user_id'] != user_id:
            return None
        if now - item['created'] > SMART_FILL_PREVIEW_TTL_SECONDS:
            del _smart_fill_preview_store[token]
            return None
        return item


def _remove_smart_fill_preview(token: str) -> None:
    with _smart_fill_preview_lock:
        _smart_fill_preview_store.pop(token, None)


def _store_smart_import_preview(user_id, template_digest, analysis) -> str:
    now = time.time()
    with _smart_import_preview_lock:
        expired = [
            token for token, item in _smart_import_preview_store.items()
            if now - item['created'] > SMART_FILL_PREVIEW_TTL_SECONDS
        ]
        for token in expired:
            del _smart_import_preview_store[token]
        while len(_smart_import_preview_store) >= SMART_FILL_PREVIEW_MAX_ENTRIES:
            oldest = min(
                _smart_import_preview_store,
                key=lambda token: _smart_import_preview_store[token]['created'],
            )
            del _smart_import_preview_store[oldest]
        token = uuid.uuid4().hex
        _smart_import_preview_store[token] = {
            'user_id': user_id,
            'template_digest': template_digest,
            'analysis': analysis,
            'created': now,
        }
    return token


def _get_smart_import_preview(token: str, user_id):
    now = time.time()
    with _smart_import_preview_lock:
        item = _smart_import_preview_store.get(token)
        if not item or item['user_id'] != user_id:
            return None
        if now - item['created'] > SMART_FILL_PREVIEW_TTL_SECONDS:
            del _smart_import_preview_store[token]
            return None
        return item


def _remove_smart_import_preview(token: str) -> None:
    with _smart_import_preview_lock:
        _smart_import_preview_store.pop(token, None)


def _smart_fill_filename(original_filename: str) -> str:
    original_stem = os.path.splitext(os.path.basename(original_filename))[0]
    safe_stem = re.sub(r'[\\/:*?"<>|\r\n]+', '_', original_stem).strip(' .') or '工资表'
    return f'{safe_stem}_已填.xlsx'


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


    @app.route('/api/smart-import-preview', methods=['POST'])
    @login_required
    def smart_import_preview():
        """识别任意员工信息表的字段映射，并返回新增/更新/恢复预览。"""
        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请选择要智能导入的 Excel 文件')
        if os.path.splitext(file.filename)[1].lower() not in ALLOWED_UPLOAD_EXTENSIONS:
            return api_err('智能导入仅支持 .xlsx 格式文件')

        try:
            template_bytes = file.read()
            analysis, preview = prepare_smart_import(template_bytes)
        except (TemplateAnalysisError, TemplateFillError) as exc:
            sys_log.warning('用户 %s 智能导入预览未完成: %s', session.get('username'), exc)
            return api_err(str(exc), status=422)
        except Exception:
            sys_log.exception('用户 %s 智能导入预览失败', session.get('username'))
            return api_err('智能导入预览失败，请查看系统日志；标准导入仍可继续使用', status=500)

        token = _store_smart_import_preview(
            session.get('user_id'), hashlib.sha256(template_bytes).hexdigest(), analysis,
        )
        sys_log.info(
            '用户 %s 完成智能导入预览: 文件=%s, 总行=%s, 新增=%s, 更新=%s, 恢复=%s, 错误=%s',
            session.get('username'), file.filename, preview['summary']['total'],
            preview['summary']['new'], preview['summary']['update'],
            preview['summary']['restore'], preview['summary']['error'],
        )
        return api_ok(
            '智能识别完成，请核对字段映射、数据和导入范围',
            preview_token=token,
            expires_in=SMART_FILL_PREVIEW_TTL_SECONDS,
            preview=preview,
        )


    @app.route('/api/smart-import-confirm', methods=['POST'])
    @login_required
    def smart_import_confirm():
        """重新接收同一客户端文件，并按用户选择执行新增、更新和恢复。"""
        token = str(request.form.get('preview_token') or '').strip()
        if not token:
            return api_err('缺少智能导入预览凭证')
        item = _get_smart_import_preview(token, session.get('user_id'))
        if item is None:
            return api_err('智能导入预览已过期或不存在，请重新识别文件', status=404)

        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请重新提交已预览的 Excel 文件')
        if os.path.splitext(file.filename)[1].lower() not in ALLOWED_UPLOAD_EXTENSIONS:
            return api_err('智能导入仅支持 .xlsx 格式文件')
        template_bytes = file.read()
        if hashlib.sha256(template_bytes).hexdigest() != item['template_digest']:
            return api_err('当前文件与智能导入预览时不一致，请重新识别文件', status=409)

        allowed_statuses = {
            status for status, form_name in (
                ('new', 'allow_new'), ('update', 'allow_update'), ('restore', 'allow_restore')
            )
            if str(request.form.get(form_name, '')).lower() in {'1', 'true', 'on', 'yes'}
        }
        try:
            result = execute_smart_import(template_bytes, item['analysis'], allowed_statuses)
        except (TemplateAnalysisError, TemplateFillError) as exc:
            sys_log.warning('用户 %s 智能导入确认未完成: %s', session.get('username'), exc)
            return api_err(str(exc), status=422)
        except Exception:
            sys_log.exception('用户 %s 智能导入确认失败', session.get('username'))
            return api_err('智能导入失败，请查看系统日志；标准导入仍可继续使用', status=500)

        _remove_smart_import_preview(token)
        db_log.info('用户 %s 智能导入员工: %s', session.get('username'), result)
        return api_ok('智能导入完成', **result)


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


    @app.route('/api/smart-fill', methods=['POST'])
    @login_required
    def smart_fill_requires_preview():
        """旧的直接写入入口不再允许绕过映射确认。"""
        return api_err('智能填表需要先预览并确认字段映射', status=409)


    @app.route('/api/smart-fill-preview', methods=['POST'])
    @login_required
    def smart_fill_preview():
        """识别工资表模板，返回经过服务端校验的字段映射供用户确认。"""
        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请选择要填写的 Excel 模板')
        if os.path.splitext(file.filename)[1].lower() not in ALLOWED_UPLOAD_EXTENSIONS:
            return api_err('智能填表仅支持 .xlsx 格式文件')

        raw_names = request.form.get('names', '')
        names = []
        if raw_names:
            try:
                parsed_names = json.loads(raw_names)
            except json.JSONDecodeError:
                return api_err('姓名名单格式不正确')
            if not isinstance(parsed_names, list):
                return api_err('姓名名单格式不正确')
            names = list(dict.fromkeys(
                str(name).strip() for name in parsed_names if str(name).strip()
            ))
            if len(names) > MAX_FILL_ROWS:
                return api_err(f'智能填表一次最多支持 {MAX_FILL_ROWS} 个姓名')

        try:
            template_bytes = file.read()
            analysis, preview = prepare_template(template_bytes)
        except (TemplateAnalysisError, TemplateFillError) as exc:
            sys_log.warning('用户 %s 智能填表预览未完成: %s', session.get('username'), exc)
            return api_err(str(exc), status=422, fallback_available=True)
        except Exception:
            sys_log.exception('用户 %s 智能填表预览失败', session.get('username'))
            return api_err('智能填表预览失败，请查看系统日志；现有手动导出仍可使用',
                           status=500, fallback_available=True)

        token = _store_smart_fill_preview(
            session.get('user_id'), hashlib.sha256(template_bytes).hexdigest(), names, analysis,
        )
        sys_log.info(
            '用户 %s 完成智能填表映射预览: 文件=%s, 表格=%s, 置信度=%.2f',
            session.get('username'), file.filename, len(preview['tables']),
            preview['confidence'],
        )
        return api_ok(
            '模板识别完成，请核对字段映射后确认填写',
            preview_token=token,
            expires_in=SMART_FILL_PREVIEW_TTL_SECONDS,
            preview=preview,
            name_mode='provided' if names else 'template',
            requested_names=len(names),
        )


    @app.route('/api/smart-fill-confirm', methods=['POST'])
    @login_required
    def smart_fill_confirm():
        """接收客户端再次上传的模板，并使用预览阶段的已验证映射执行填表。"""
        token = str(request.form.get('preview_token') or '').strip()
        if not token:
            return api_err('缺少智能填表预览凭证')
        item = _get_smart_fill_preview(token, session.get('user_id'))
        if item is None:
            return api_err('预览已过期或不存在，请重新识别模板', status=404)

        file = request.files.get('file')
        if not file or not file.filename:
            return api_err('请重新提交已预览的 Excel 模板')
        if os.path.splitext(file.filename)[1].lower() not in ALLOWED_UPLOAD_EXTENSIONS:
            return api_err('智能填表仅支持 .xlsx 格式文件')
        template_bytes = file.read()
        if hashlib.sha256(template_bytes).hexdigest() != item['template_digest']:
            return api_err('当前模板与映射预览时的文件不一致，请重新识别模板', status=409)

        try:
            output_bytes, summary, analysis = fill_template(
                template_bytes, names=item['names'], analysis=item['analysis'],
            )
        except (TemplateAnalysisError, TemplateFillError) as exc:
            sys_log.warning('用户 %s 确认智能填表未完成: %s', session.get('username'), exc)
            return api_err(str(exc), status=422, fallback_available=True)
        except Exception:
            sys_log.exception('用户 %s 确认智能填表失败', session.get('username'))
            return api_err('智能填表失败，请查看系统日志；现有手动导出仍可使用',
                           status=500, fallback_available=True)

        _remove_smart_fill_preview(token)
        filename = _smart_fill_filename(file.filename)
        response = send_file(
            io.BytesIO(output_bytes), as_attachment=True, download_name=filename,
            mimetype=EXPORT_MIMETYPE,
        )
        response.headers['X-Smart-Fill-Matched'] = str(summary['matched'])
        response.headers['X-Smart-Fill-Missing'] = str(len(summary['missing']))
        response.headers['X-Smart-Fill-Cells'] = str(summary['cells_filled'])
        response.headers['X-Smart-Fill-Confidence'] = f"{analysis['confidence']:.2f}"
        sys_log.info(
            '用户 %s 智能填表: 文件=%s, 匹配=%s, 填写单元格=%s, 置信度=%.2f',
            session.get('username'), file.filename, summary['matched'],
            summary['cells_filled'], analysis['confidence'],
        )
        return response


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
