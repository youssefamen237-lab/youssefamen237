import sqlite3
import os

# Database initialization
DB_PATH = 'data.db'

# Initialize database
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create used_questions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS used_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create published_videos table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS published_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            thumbnail TEXT NOT NULL,
            video_id TEXT UNIQUE,
            published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            views INTEGER DEFAULT 0,
            watch_time INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0.0,
            retention REAL DEFAULT 0.0
        )
    ''')
    
    # Create performance_metrics table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS performance_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            views INTEGER NOT NULL,
            watch_time INTEGER NOT NULL,
            ctr REAL NOT NULL,
            retention REAL NOT NULL,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (video_id) REFERENCES published_videos (id)
        )
    ''')
    
    # Create video_templates table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_name TEXT UNIQUE NOT NULL,
            template_data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Check if question was already used
def is_question_used(question):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM used_questions WHERE question = ?', (question,))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

# Mark question as used
def mark_question_as_used(question):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO used_questions (question) VALUES (?)', (question,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# Check if video was already published
def is_video_published(title, description, thumbnail):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM published_videos WHERE title = ? AND description = ? AND thumbnail = ?', 
                   (title, description, thumbnail))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

# Record published video
def record_published_video(title, description, thumbnail, video_id=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO published_videos (title, description, thumbnail, video_id) 
            VALUES (?, ?, ?, ?)
        ''', (title, description, thumbnail, video_id))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"Error recording published video: {e}")
        return None
    finally:
        conn.close()

# Update video performance metrics
def update_video_performance(video_id, views, watch_time, ctr, retention):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO performance_metrics (video_id, views, watch_time, ctr, retention) 
            VALUES (?, ?, ?, ?, ?)
        ''', (video_id, views, watch_time, ctr, retention))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating performance metrics: {e}")
        return False
    finally:
        conn.close()

# Get all used questions
def get_all_used_questions():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT question FROM used_questions')
    questions = [row[0] for row in cursor.fetchall()]
    conn.close()
    return questions

# Get recent videos for analysis
def get_recent_videos(limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, description, thumbnail, views, watch_time, ctr, retention 
        FROM published_videos ORDER BY published_at DESC LIMIT ?
    ''', (limit,))
    videos = cursor.fetchall()
    conn.close()
    return videos

# Initialize the database on startup
if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
