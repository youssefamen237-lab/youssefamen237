import sqlite3

# Connect to the database
conn = sqlite3.connect('database.db')

# Create a cursor object
cur = conn.cursor()

# Create tables
cur.execute('''
    CREATE TABLE IF NOT EXISTS used_questions (
        id INTEGER PRIMARY KEY,
        question TEXT NOT NULL
    )
''')

cur.execute('''
    CREATE TABLE IF NOT EXISTS published_videos (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        thumbnail TEXT NOT NULL
    )
''')

cur.execute('''
    CREATE TABLE IF NOT EXISTS performance_metrics (
        id INTEGER PRIMARY KEY,
        video_id INTEGER NOT NULL,
        views INTEGER NOT NULL,
        watch_time INTEGER NOT NULL,
        ctr REAL NOT NULL,
        retention REAL NOT NULL,
        FOREIGN KEY (video_id) REFERENCES published_videos (id)
    )
''')

# Commit the changes
conn.commit()

# Close the connection
conn.close()