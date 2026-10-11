"""Excel 业务服务。

这里不依赖 Flask request/response；路由层只负责把上传内容传进来，
以及把返回的 bytes 交给 send_file。
"""

import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime

from core import config
from core.app_common import ALLOWED_UPLOAD_EXTENSIONS
from services.excel_utils import (
    IMPORT_COLUMNS, build_export_buffer, classify_import_rows, import_employee_rows,
    read_employee_excel, read_names, summarize_import_rows,
)
from core.log_utils import db_log, sys_log
from services.smart_import_service import execute_smart_import, prepare_smart_import
from services.smart_fill_service import (
    MAX_FILL_ROWS, TemplateAnalysisError, TemplateFillError, fill_template,
    prepare_template, normalize_template_bytes,
)

EXPORT_MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
PREVIEW_TTL_SECONDS = 10 * 60
PREVIEW_MAX_ENTRIES = 20

_stores = {'smart_fill': {}, 'smart_import': {}}
_locks = {'smart_fill': threading.Lock(), 'smart_import': threading.Lock()}
# 兼容旧测试和调试代码：预览缓存的真实归属已移到服务层。
_smart_fill_preview_store = _stores['smart_fill']
_smart_import_preview_store = _stores['smart_import']


def validate_xlsx_filename(filename: str, smart_label='文件'):
    if not filename:
        return False
    return os.path.splitext(filename)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def preview_import(stream):
    rows = read_employee_excel(stream)
    if not rows:
        raise ValueError('文件中没有数据行')
    rows = classify_import_rows(rows)
    return rows, summarize_import_rows(rows)


def confirm_import(raw_rows, username):
    cleaned = []
    for raw in raw_rows:
        row = {'_row': raw.get('_row', 0)}
        for field in IMPORT_COLUMNS:
            row[field] = str(raw.get(field, '') or '').strip()
        cleaned.append(row)
    rows = classify_import_rows(cleaned)
    result = import_employee_rows(rows)
    db_log.info('用户 %s 导入员工: %s', username, result)
    return result


def _store(kind, user_id, **item):
    now = time.time()
    store, lock = _stores[kind], _locks[kind]
    with lock:
        expired = [token for token, value in store.items()
                   if now - value['created'] > PREVIEW_TTL_SECONDS]
        for token in expired:
            del store[token]
        while len(store) >= PREVIEW_MAX_ENTRIES:
            oldest = min(store, key=lambda token: store[token]['created'])
            del store[oldest]
        token = uuid.uuid4().hex
        store[token] = {'user_id': user_id, 'created': now, **item}
        return token


def _get(kind, token, user_id):
    now = time.time()
    store, lock = _stores[kind], _locks[kind]
    with lock:
        item = store.get(token)
        if not item or item['user_id'] != user_id:
            return None
        if now - item['created'] > PREVIEW_TTL_SECONDS:
            del store[token]
            return None
        return item


def _remove(kind, token):
    with _locks[kind]:
        _stores[kind].pop(token, None)


def store_smart_import_preview(user_id, template_digest, analysis):
    return _store(
        'smart_import', user_id, template_digest=template_digest, analysis=analysis,
    )


def store_smart_fill_preview(user_id, template_digest, names, analysis):
    return _store(
        'smart_fill', user_id, template_digest=template_digest,
        names=names, analysis=analysis,
    )


def preview_smart_import(template_bytes, user_id, prepare_fn=prepare_smart_import):
    analysis, preview = prepare_fn(template_bytes)
    token = _store(
        'smart_import', user_id,
        template_digest=hashlib.sha256(template_bytes).hexdigest(), analysis=analysis,
    )
    return token, preview


def confirm_smart_import(token, user_id, template_bytes, allowed_statuses, username,
                         execute_fn=execute_smart_import):
    item = _get('smart_import', token, user_id)
    if item is None:
        raise LookupError('智能导入预览已过期或不存在，请重新识别文件')
    digest = hashlib.sha256(template_bytes).hexdigest()
    if digest != item['template_digest']:
        raise ValueError('当前文件与智能导入预览时不一致，请重新识别文件')
    result = execute_fn(template_bytes, item['analysis'], allowed_statuses)
    _remove('smart_import', token)
    db_log.info('用户 %s 智能导入员工: %s', username, result)
    return result


def export_names(names, action, username):
    buf, total, matched = build_export_buffer(names)
    sys_log.info('用户 %s %s: 共 %s 条，匹配 %s 条', username, action, total, matched)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return buf, f'导出信息_{stamp}.xlsx'


def input_preview():
    names = read_names(config.INPUT_XLSX, limit=20)
    return [{'姓名': name} for name in names]


def parse_names(raw_names):
    if not raw_names:
        return []
    try:
        parsed = json.loads(raw_names)
    except json.JSONDecodeError as exc:
        raise ValueError('姓名名单格式不正确') from exc
    if not isinstance(parsed, list):
        raise ValueError('姓名名单格式不正确')
    names = list(dict.fromkeys(str(name).strip() for name in parsed if str(name).strip()))
    if len(names) > MAX_FILL_ROWS:
        raise ValueError(f'智能填表一次最多支持 {MAX_FILL_ROWS} 个姓名')
    return names


def preview_smart_fill(template_bytes, names, user_id, prepare_fn=prepare_template,
                       overwrite=False):
    if overwrite and not names:
        raise TemplateFillError('清空重填模式必须提供姓名名单，请先在下方添加姓名')
    normalized = normalize_template_bytes(template_bytes)
    analysis, preview = prepare_fn(normalized)
    converted = normalized is not template_bytes
    preview = {**preview, 'source_format': 'xls' if converted else 'xlsx',
               'output_format': 'xlsx', 'converted': converted}
    token = _store(
        'smart_fill', user_id,
        template_digest=hashlib.sha256(template_bytes).hexdigest(),
        names=names, analysis=analysis, overwrite=bool(overwrite),
        converted_template=normalized if converted else None,
    )
    return token, preview


def _smart_fill_filename(original_filename):
    stem = os.path.splitext(os.path.basename(original_filename))[0]
    safe = re.sub(r'[\\/:*?"<>|\r\n]+', '_', stem).strip(' .') or '工资表'
    return f'{safe}_已填.xlsx'


def confirm_smart_fill(token, user_id, template_bytes, original_filename, username,
                       fill_fn=fill_template):
    item = _get('smart_fill', token, user_id)
    if item is None:
        raise LookupError('预览已过期或不存在，请重新识别模板')
    if hashlib.sha256(template_bytes).hexdigest() != item['template_digest']:
        raise ValueError('当前模板与映射预览时的文件不一致，请重新识别模板')
    fill_options = {'names': item['names'], 'analysis': item['analysis']}
    if item.get('overwrite', False):
        fill_options['overwrite'] = True
    output_bytes, summary, analysis = fill_fn(
        item.get('converted_template') or template_bytes, **fill_options,
    )
    _remove('smart_fill', token)
    sys_log.info(
        '用户 %s 智能填表: 文件=%s, 匹配=%s, 填写单元格=%s, 置信度=%.2f',
        username, original_filename, summary['matched'], summary['cells_filled'],
        analysis['confidence'],
    )
    return output_bytes, summary, analysis, _smart_fill_filename(original_filename)
