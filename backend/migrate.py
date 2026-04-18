import sqlite3

def add_column_if_not_exists(cursor, table_name, column_name, column_type):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in cursor.fetchall()]
    if column_name not in columns:
        print(f"Adding {column_name} to {table_name}")
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

conn = sqlite3.connect('safespace.db')
cursor = conn.cursor()

try:
    add_column_if_not_exists(cursor, 'mood_logs', 'keywords', 'VARCHAR DEFAULT ""')
    add_column_if_not_exists(cursor, 'chat_messages', 'mood_score', 'INTEGER')
    add_column_if_not_exists(cursor, 'chat_sessions', 'aggregated_score', 'INTEGER')
    add_column_if_not_exists(cursor, 'chat_sessions', 'title', 'VARCHAR')
    add_column_if_not_exists(cursor, 'chat_sessions', 'started_at', 'DATETIME DEFAULT CURRENT_TIMESTAMP')
    
    # We should also check for daily_summaries and user_summaries tables
    # Since they might not exist, creating them here or just letting sqlalchemy do it
    # Calling sqlalchemy's create_all will create missing tables, but not missing columns.
    
    conn.commit()
    print("Migration successful.")
except Exception as e:
    print(f"Error migrating: {e}")
finally:
    conn.close()
