"""
员工信息命令行查询工具
按姓名或拼音首字母精确查询，输入 0 退出。

用法:
    python gzb_find.py
"""

from db import init_db, query_all

FIELDS = [('姓名', 'real_name'), ('身份证号', 'id_number'), ('银行账号', 'bank_account'),
          ('银行地址', 'bank_address'), ('电话', 'phone')]


def search_employee(keyword: str) -> list:
    """按姓名或拼音首字母精确匹配在职员工信息（不含已软删除记录）。"""
    return query_all(
        "SELECT real_name, id_number, bank_account, bank_address, phone, sx "
        "FROM employees WHERE deleted = 0 AND (real_name = ? OR sx = ?)",
        (keyword, keyword)
    )


def main() -> None:
    init_db()
    while True:
        keyword = input("请输入要查询的姓名（输入 0 退出）：").strip()
        if keyword in ('0', ''):
            break

        results = search_employee(keyword)
        if not results:
            print("未找到该姓名的记录。")
            continue

        for row in results:
            print('-' * 40)
            for label, key in FIELDS:
                print(f"  {label}: {row[key] or ''}")
        print('-' * 40)


if __name__ == '__main__':
    main()
