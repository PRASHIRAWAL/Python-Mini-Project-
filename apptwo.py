import sqlite3

conn = sqlite3.connect('expense_splitter.db', check_same_thread=False)
c = conn.cursor()
# Do something with the database
conn.commit()
conn.close()
