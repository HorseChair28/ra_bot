import sqlite3
from datetime import datetime
from typing import List, Dict, Any

DB_PATH="shifts.db"


def init_db():
    """Инициализация базы данных"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor=conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                date TEXT,
                role TEXT,
                program TEXT,
                start_time TEXT,
                end_time TEXT,
                salary INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def save_shift(user_id, shift_data):
    """Сохраняет смену"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor=conn.cursor()
        cursor.execute("""
            INSERT INTO shifts (user_id, date, role, program, start_time, end_time, salary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            shift_data.get("date").isoformat() if shift_data.get("date") else None,
            shift_data.get("role"),
            shift_data.get("program"),
            shift_data.get("start_time"),
            shift_data.get("end_time"),
            shift_data.get("salary")
        ))
        conn.commit()


def get_user_shifts(user_id):
    """Возвращает список смен пользователя"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory=sqlite3.Row
        cursor=conn.cursor()
        cursor.execute("""
            SELECT id, user_id, date, role, program, start_time, end_time, salary, created_at
            FROM shifts 
            WHERE user_id = ? 
            ORDER BY date DESC, start_time DESC
        """, (user_id,))
        rows=cursor.fetchall()

        shifts=[]
        for row in rows:
            shift=dict(row)
            # Конвертируем строку даты в объект date для бота
            if shift.get('date'):
                try:
                    shift['date']=datetime.fromisoformat(shift['date']).date()
                except:
                    shift['date']=None
            shifts.append(shift)

        return shifts


def get_all_shifts() -> List[Dict[str, Any]]:
    """Возвращает все смены из базы данных (для веб-интерфейса)"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory=sqlite3.Row
            cursor=conn.cursor()
            cursor.execute("""
                SELECT id, user_id, date, role, program, start_time, end_time, salary, created_at
                FROM shifts
                ORDER BY date DESC, start_time DESC
            """)
            rows=cursor.fetchall()

            shifts=[]
            for row in rows:
                shift=dict(row)
                # Оставляем дату как строку для JSON API
                # НЕ конвертируем в date объект
                shifts.append(shift)

            print(f"[DEBUG] get_all_shifts вернула {len(shifts)} смен")
            return shifts

    except Exception as e:
        print(f"Ошибка при получении всех смен: {e}")
        return []


def delete_shift(user_id, shift_id):
    """Удаляет смену по ID"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor=conn.cursor()
        cursor.execute("DELETE FROM shifts WHERE user_id = ? AND id = ?", (user_id, shift_id))
        conn.commit()
        return cursor.rowcount>0


def update_shift(user_id: str, shift_id: int, field: str, value: Any) -> bool:
    """Обновление поля смены"""
    try:
        # Специальная обработка для поля date
        if field == 'date':
            if value and hasattr(value, 'isoformat'):
                # Если передан объект date, конвертируем в строку
                value=value.isoformat()
            # Если передана строка или None - оставляем как есть

        with sqlite3.connect(DB_PATH) as conn:
            # Используем параметризованный запрос для безопасности
            query=f'UPDATE shifts SET {field} = ? WHERE id = ? AND user_id = ?'
            cursor=conn.execute(query, (value, shift_id, user_id))
            conn.commit()

            if cursor.rowcount>0:
                print(f"[DEBUG] Успешно обновлено поле {field} = {value} для смены {shift_id}")
                return True
            else:
                print(f"[ERROR] Смена {shift_id} не найдена или не принадлежит пользователю {user_id}")
                return False

    except Exception as e:
        print(f"Ошибка при обновлении смены: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_statistics() -> Dict[str, Any]:
    """Получение статистики по всем сменам"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor=conn.execute('''
                SELECT 
                    COUNT(*) as total_shifts,
                    COUNT(DISTINCT user_id) as total_users,
                    SUM(salary) as total_salary,
                    AVG(salary) as avg_salary
                FROM shifts
                WHERE salary IS NOT NULL
            ''')

            row=cursor.fetchone()
            return {
                'total_shifts': row[0] or 0,
                'total_users': row[1] or 0,
                'total_salary': row[2] or 0,
                'avg_salary': round(row[3] or 0)
            }

    except Exception as e:
        print(f"Ошибка при получении статистики: {e}")
        return {
            'total_shifts': 0,
            'total_users': 0,
            'total_salary': 0,
            'avg_salary': 0
        }