import sqlite3
# 创建或连接数据库
conn = sqlite3.connect("sjk.db")
while True:
    name = input("请输入要查询的姓名（输入'0'退出）：")
    if name.lower() == '0':
        break


    # 执行查询
    cursor = conn.execute("SELECT * FROM employees WHERE real_name=? or sx=?", (name, name))
    result = cursor.fetchall()      

    if result:
        for row in result:
            print(f'''
                  姓名: {row[0]}, 
                  身份证号: {row[1]}, 
                  银行账号: {row[2]},
                  银行地址: {row[3]}, 
                  电话: {row[4]}
                  ''')
    else:
        print("未找到该姓名的记录。")

    # 关闭连接
conn.close()