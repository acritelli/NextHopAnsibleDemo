import sqlite3

##### CONFIG VARS #####
NUM_AVAIL_DEMOS = 10
##### END CONFIG VARS #####

conn = sqlite3.connect('labDatabase.db')
cur = conn.cursor()
cur.execute('DROP TABLE IF EXISTS labconfig')
cur.execute("CREATE TABLE labConfig (param TEXT, value INT)")
cur.execute("INSERT INTO labConfig values (?, ?)", ("availableDemos", NUM_AVAIL_DEMOS))
conn.commit()
conn.close()
