"""
Excel 员工信息批量导入工具
从 Excel 读取员工数据写入数据库：姓名已存在则更新，否则新增；
已删除的同名记录自动恢复。自动识别中英文表头，文本列保留前导零。

用法:
    python gzb_update.py              # 默认导入 aaa.xlsx
    python gzb_update.py data.xlsx    # 指定 Excel 文件
"""

import os
import sys

from db import init_db
from excel_utils import read_employee_excel, classify_import_rows, import_employee_rows


def import_excel(path: str) -> None:
    """从指定 Excel 文件导入员工信息，并打印分类统计与错误行明细。"""
    if not os.path.exists(path):
        print(f"错误：文件 {path} 不存在")
        return

    try:
        rows = read_employee_excel(path)
    except ValueError as e:
        print(f"错误：{e}")
        return

    if not rows:
        print("文件中没有数据行")
        return

    init_db()
    rows = classify_import_rows(rows)
    result = import_employee_rows(rows)

    # 打印错误行明细，便于修正源文件
    error_rows = [r for r in rows if r['status'] == 'error']
    for r in error_rows:
        print(f"  第 {r['_row']} 行 [{r['real_name'] or '(空)'}]: {'；'.join(r['messages'])}")

    print(f"导入完成：新增 {result['inserted']} 条，更新 {result['updated']} 条，"
          f"恢复 {result['restored']} 条，跳过 {result['skipped']} 条"
          f"（其中错误行 {len(error_rows)} 条）")


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else 'aaa.xlsx'
    import_excel(path)


if __name__ == '__main__':
    main()
