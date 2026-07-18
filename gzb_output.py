import sqlite3
import pandas as pd
conn = sqlite3.connect("sjk.db")
##看看是要哪个文件读入数据
df= pd.read_excel('input.xlsx')

# 输出一个已经有名字的表格
sql_real_name = conn.execute("SELECT real_name FROM employees").fetchall()
existing_names = [name[0] for name in sql_real_name]  # 转换为列表
for i in range(len(df)):
    if df['姓名'][i] in existing_names:
        #各个数据
        cursor = conn.execute("SELECT * FROM employees WHERE real_name=?", (df['姓名'][i],))
        result = cursor.fetchall()

        for row in result:
            print(f'''
                  姓名: {row[0]}, 
                  身份证号: {row[1]}, 
                  银行账号: {row[2]},
                  银行地址: {row[3]}, 
                  电话: {row[4]}
                  ''')
        #开始写入
        df.loc[i, '身份证号'] = result[0][1]
        df.loc[i, '银行账号'] = result[0][2]
        df.loc[i, '银行地址'] = result[0][3]
        df.loc[i, '电话'] = result[0][4]
    else: #开始写入
        df.loc[i, '身份证号'] = 0
        df.loc[i, '银行账号'] = 0
        df.loc[i, '银行地址'] = 0
        df.loc[i, '电话'] = 0
# 保存回 Excel
df.to_excel('output.xlsx', index=False, engine='openpyxl')
