"""Native XLS template conversion; never use the values-only import adapter here."""

import io
import os
import struct
import subprocess
import tempfile
import threading
from pathlib import Path

import xlrd
from xlrd.compdoc import CompDoc

from services.legacy_excel import OLE_MAGIC, MAX_LEGACY_CELLS

MAX_TEMPLATE_BYTES = 5 * 1024 * 1024
MAX_CONVERTED_BYTES = 10 * 1024 * 1024
CONVERSION_TIMEOUT = 60
_conversion_lock = threading.Lock()
_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'convert_legacy_template.ps1'


class LegacyTemplateError(ValueError):
    """Conversion could not safely preserve the template."""


def _validate_biff_stream(stream):
    offset = 0
    while offset + 4 <= len(stream):
        record, length = struct.unpack_from('<HH', stream, offset)
        offset += 4
        if offset + length > len(stream):
            raise LegacyTemplateError('XLS 模板记录损坏，请用 Excel 另存为 .xlsx 后重试')
        payload = stream[offset:offset + length]
        offset += length
        if record == 0x002F:  # FILEPASS
            raise LegacyTemplateError('不支持加密的 XLS 模板，请解除密码后另存为 .xlsx')
        if record == 0x00D3:  # ObProj: VBA project marker, even if storage is damaged.
            raise LegacyTemplateError('不支持包含宏的 XLS 模板，请移除宏后另存为 .xlsx')
        # Qsi / DConn / DbOrParamQry / DBQueryExt / OleDbConn can refresh on open,
        # independently of UpdateLinks=0 and manual formula calculation.
        if record in (0x01AD, 0x0876, 0x00DC, 0x0803, 0x080A):
            raise LegacyTemplateError('不支持带外部数据连接的 XLS 模板，请去除连接或另存为 .xlsx')
        if record == 0x01AE:  # SupBook: allow only ordinary internal references.
            if len(payload) < 4 or struct.unpack_from('<H', payload, 2)[0] != 0x0401:
                raise LegacyTemplateError('不支持带外部引用或加载项的 XLS 模板，请另存为 .xlsx')
        if record == 0x0085:  # BOUNDSHEET: type 1=XLM, 6=VBA module
            if len(payload) < 6 or payload[5] not in (0, 2):
                raise LegacyTemplateError('不支持包含宏的 XLS 模板，请移除宏后另存为 .xlsx')
        if record == 0x0809 and len(payload) >= 4:
            if struct.unpack_from('<H', payload, 2)[0] not in (0x0005, 0x0010, 0x0020):
                raise LegacyTemplateError('不支持包含宏或特殊子表的 XLS 模板')


def validate_legacy_template(raw):
    if not raw.startswith(OLE_MAGIC) or len(raw) > MAX_TEMPLATE_BYTES:
        raise LegacyTemplateError('请选择有效的 .xls 工资表模板（不超过 5MB）')
    try:
        compound = CompDoc(raw, logfile=io.StringIO())
        # AutomationSecurity does not disable Excel 4 macros: reject before opening.
        forbidden = {'vba', '_vba_project', '_vba_project_cur', 'project', 'projectwm',
                     'objectpool'}
        if any(entry.name.lower() in forbidden for entry in compound.dirlist):
            raise LegacyTemplateError('不支持包含宏或嵌入对象的 XLS 模板，请另存为无宏 .xlsx')
        stream = compound.get_named_stream('Workbook') or compound.get_named_stream('Book')
        if not stream:
            raise LegacyTemplateError('文件不是有效的 Excel XLS 模板')
        _validate_biff_stream(stream)
        workbook = xlrd.open_workbook(file_contents=raw, on_demand=True, logfile=io.StringIO())
        try:
            cells = 0
            for index in range(workbook.nsheets):
                sheet = workbook.sheet_by_index(index)
                cells += sheet.nrows * sheet.ncols
                if cells > MAX_LEGACY_CELLS:
                    raise LegacyTemplateError('XLS 模板表格范围过大，无法安全处理')
        finally:
            workbook.release_resources()
    except LegacyTemplateError:
        raise
    except Exception:
        raise LegacyTemplateError('XLS 模板解析失败，请用 Excel 另存为 .xlsx 后重试') from None


def _run_conversion(source, target, owner):
    command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(_SCRIPT),
               '-Source', str(source), '-Target', str(target), '-OwnerFile', str(owner)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=CONVERSION_TIMEOUT,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        # Only the newly created Excel process recorded by our worker can be stopped.
        try:
            subprocess.run(command + ['-CleanupOnly'], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise LegacyTemplateError('XLS 模板转换超时，请在 Excel 中另存为 .xlsx 后重试') from None
    except OSError:
        raise LegacyTemplateError('XLS 模板转换需要 Windows 和已安装的 Microsoft Excel；也可另存为 .xlsx 上传') from None
    if result.returncode == 3:
        raise LegacyTemplateError('服务器无法启动 Microsoft Excel，XLS 模板转换不可用；请安装 Excel 或另存为 .xlsx 上传')
    if result.returncode != 0 or not target.is_file():
        raise LegacyTemplateError('XLS 模板转换失败（可能有密码、损坏或特殊内容），请用 Excel 另存为 .xlsx 后重试')
    if target.stat().st_size > MAX_CONVERTED_BYTES:
        raise LegacyTemplateError('XLS 模板转换后的文件过大，无法安全处理')
    output = target.read_bytes()
    if not output.startswith(b'PK'):
        raise LegacyTemplateError('XLS 模板转换结果无效，请另存为 .xlsx 后重试')
    return output


def convert_legacy_template(raw):
    validate_legacy_template(raw)
    if os.name != 'nt':
        raise LegacyTemplateError('XLS 模板转换需要 Windows 和 Microsoft Excel；请另存为 .xlsx 上传')
    if not _conversion_lock.acquire(timeout=5):
        raise LegacyTemplateError('其他 XLS 模板正在转换，请稍后重新识别')
    try:
        with tempfile.TemporaryDirectory(prefix='gzd-xls-template-') as directory:
            folder = Path(directory)
            source, target = folder / 'source.xls', folder / 'converted.xlsx'
            source.write_bytes(raw)
            return _run_conversion(source, target, folder / 'excel-owner.json')
    finally:
        _conversion_lock.release()
