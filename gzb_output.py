"""
员工信息批量导出脚本
读取 input.xlsx 中的姓名列表，匹配数据库信息后导出到 output.xlsx。
数据库中不存在的姓名导出为空行。

用法:
    python gzb_output.py
"""

import config
from excel_utils import read_names, export_employees


def main() -> None:
    try:
        names = read_names(config.INPUT_XLSX)
    except FileNotFoundError as e:
        print(f"错误：{e}")
        return

    if not names:
        print("input.xlsx 中没有姓名数据")
        return

    total, matched = export_employees(names, config.OUTPUT_XLSX)
    print(f"导出完成：共 {total} 条，其中 {matched} 条匹配到数据 -> {config.OUTPUT_XLSX}")


if __name__ == '__main__':
    main()
