import sqlite3
import pandas as pd
from pypinyin import pinyin, lazy_pinyin, Style
# 创建或连接数据库
conn = sqlite3.connect("test.db")
##看看是要哪个文件读入数据
df= pd.read_excel('aaa.xlsx', dtype={'phone': str})
# df = pd.read_csv('employees(2).csv', dtype={'phone': str})

def create():
            #创建表（如果不存在）
            conn.execute('''
            CREATE TABLE IF NOT EXISTS employees(
                real_name text,
                id_number text,
                bank_account text,
                bank_address text,
                phone text
            )
            ''')
            conn.commit()  # 提交创建表的操作

# 获取数据库中已存在的姓名
sql_real_name = conn.execute("SELECT real_name FROM employees").fetchall()
existing_names = [name[0] for name in sql_real_name]  # 转换为列表便于比较

# 写入新数据
for index, row in df.iterrows():
    text=row['real_name']
    result = lazy_pinyin(text, style=Style.FIRST_LETTER)
    sx = ""
    for char in result:
        sx += char.lower()
        
    if row['real_name'] not in existing_names:
        conn.execute(
            '''INSERT INTO employees
                (real_name,id_number,bank_account,bank_address,phone,sx) 
            VALUES(?,?,?,?,?,?)''',
            (row['real_name'], 
             row['id_number'], 
             row['bank_account'],
             row['bank_address'],
             row['phone'],
             sx)
        )
    else:
        conn.execute(
            '''UPDATE employees
                SET id_number=?, bank_account=?, bank_address=?, phone=?, sx=?
                WHERE real_name=?''',
            (row['id_number'], 
             row['bank_account'],
             row['bank_address'],
             row['phone'],
             sx,
             row['real_name'])
        )
# 提交所有插入操作
conn.commit()

##写模板中输入名字出结果