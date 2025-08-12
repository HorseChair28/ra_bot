import sqlite3

DB_PATH = "shifts.db"

def init_db():
    with sqlite3.connect("shifts.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                date TEXT,
                role TEXT,
                program TEXT,
                start_time TEXT,
                end_time TEXT,
                salary INTEGER
            )
        """)
        conn.commit()


def save_shift(user_id, shift_data):
    """Сохраняет смену"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO shifts (user_id, date, role, program, start_time, end_time, salary)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        shift_data.get("date"),
        shift_data.get("role"),
        shift_data.get("program"),
        shift_data.get("start_time"),
        shift_data.get("end_time"),
        shift_data.get("salary")
    ))
    conn.commit()
    conn.close()


def get_user_shifts(user_id):
    """Возвращает список смен пользователя в виде словарей"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # позволяет обращаться по ключам
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM shifts WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]  # превращаем Row в словари


def delete_shift(user_id, shift_id):
    """Удаляет смену по ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM shifts WHERE user_id = ? AND id = ?", (user_id, shift_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success