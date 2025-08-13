# database.py - Обновленная база данных с поддержкой пользователей
import sqlite3
import hashlib
import secrets
from datetime import datetime, date
from typing import Optional, Dict, Any, List
import json


class MultiUserDatabase:
    """База данных с поддержкой множества пользователей"""

    def __init__(self, db_path: str = "multiuser_shifts.db"):
        self.db_path=db_path
        self.init_database()

    def init_database(self):
        """Инициализация всех таблиц БД"""
        with sqlite3.connect(self.db_path) as conn:
            # Таблица пользователей
            conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    telegram_id TEXT UNIQUE,
                    username TEXT,
                    full_name TEXT,
                    email TEXT,
                    password_hash TEXT,
                    api_token TEXT UNIQUE,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            ''')

            # Таблица смен (уже есть user_id для связи)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS shifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    date TEXT,
                    role TEXT,
                    program TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    salary INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')

            # Таблица сессий для веб-авторизации
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')

            # Индексы для производительности
            conn.execute('CREATE INDEX IF NOT EXISTS idx_shifts_user_id ON shifts(user_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)')

            conn.commit()

    # ====== МЕТОДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ======

    def create_user_from_telegram(self, telegram_id: str, username: str = None,
                                  full_name: str = None) -> str:
        """Создание пользователя из Telegram"""
        user_id=f"tg_{telegram_id}"  # Уникальный ID на основе Telegram ID
        api_token=secrets.token_urlsafe(32)  # Генерируем API токен

        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute('''
                    INSERT INTO users (user_id, telegram_id, username, full_name, api_token)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, telegram_id, username, full_name, api_token))
                conn.commit()
                return user_id
            except sqlite3.IntegrityError:
                # Пользователь уже существует, обновляем last_login
                conn.execute('''
                    UPDATE users SET last_login = CURRENT_TIMESTAMP
                    WHERE telegram_id = ?
                ''', (telegram_id,))
                conn.commit()
                return user_id

    def create_user_from_web(self, email: str, password: str, full_name: str = None) -> Optional[str]:
        """Создание пользователя через веб-интерфейс"""
        user_id=f"web_{secrets.token_hex(8)}"
        password_hash=hashlib.sha256(password.encode()).hexdigest()
        api_token=secrets.token_urlsafe(32)

        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute('''
                    INSERT INTO users (user_id, email, password_hash, full_name, api_token)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, email, password_hash, full_name, api_token))
                conn.commit()
                return user_id
            except sqlite3.IntegrityError:
                return None  # Email уже существует

    def get_user_by_telegram_id(self, telegram_id: str) -> Optional[Dict]:
        """Получение пользователя по Telegram ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor=conn.execute('''
                SELECT user_id, username, full_name, api_token, is_active
                FROM users WHERE telegram_id = ?
            ''', (telegram_id,))
            row=cursor.fetchone()

            if row:
                return {
                    'user_id': row[0],
                    'username': row[1],
                    'full_name': row[2],
                    'api_token': row[3],
                    'is_active': row[4]
                }
            return None

    def authenticate_web_user(self, email: str, password: str) -> Optional[str]:
        """Аутентификация пользователя для веб-интерфейса"""
        password_hash=hashlib.sha256(password.encode()).hexdigest()

        with sqlite3.connect(self.db_path) as conn:
            cursor=conn.execute('''
                SELECT user_id FROM users 
                WHERE email = ? AND password_hash = ? AND is_active = 1
            ''', (email, password_hash))
            row=cursor.fetchone()

            if row:
                # Обновляем last_login
                conn.execute('''
                    UPDATE users SET last_login = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                ''', (row[0],))
                conn.commit()
                return row[0]
            return None

    def get_user_by_api_token(self, api_token: str) -> Optional[Dict]:
        """Получение пользователя по API токену"""
        with sqlite3.connect(self.db_path) as conn:
            cursor=conn.execute('''
                SELECT user_id, username, full_name, email, telegram_id
                FROM users WHERE api_token = ? AND is_active = 1
            ''', (api_token,))
            row=cursor.fetchone()

            if row:
                return {
                    'user_id': row[0],
                    'username': row[1],
                    'full_name': row[2],
                    'email': row[3],
                    'telegram_id': row[4]
                }
            return None

    # ====== МЕТОДЫ ДЛЯ СЕССИЙ ======

    def create_session(self, user_id: str, hours: int = 24) -> str:
        """Создание сессии для веб-авторизации"""
        session_id=secrets.token_urlsafe(32)
        expires_at=datetime.now().timestamp() + (hours * 3600)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO sessions (session_id, user_id, expires_at)
                VALUES (?, ?, ?)
            ''', (session_id, user_id, expires_at))
            conn.commit()

        return session_id

    def get_user_by_session(self, session_id: str) -> Optional[Dict]:
        """Получение пользователя по сессии"""
        with sqlite3.connect(self.db_path) as conn:
            cursor=conn.execute('''
                SELECT u.user_id, u.username, u.full_name, u.email, u.api_token
                FROM sessions s
                JOIN users u ON s.user_id = u.user_id
                WHERE s.session_id = ? AND s.expires_at > ? AND u.is_active = 1
            ''', (session_id, datetime.now().timestamp()))
            row=cursor.fetchone()

            if row:
                return {
                    'user_id': row[0],
                    'username': row[1],
                    'full_name': row[2],
                    'email': row[3],
                    'api_token': row[4]
                }
            return None

    def delete_session(self, session_id: str):
        """Удаление сессии (logout)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
            conn.commit()

    # ====== МЕТОДЫ ДЛЯ СМЕН (те же, что и раньше) ======

    def add_shift(self, user_id: str, shift_data: Dict[str, Any]) -> bool:
        """Добавление смены"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO shifts (user_id, date, role, program, start_time, end_time, salary)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    shift_data.get('date').isoformat() if shift_data.get('date') else None,
                    shift_data.get('role'),
                    shift_data.get('program'),
                    shift_data.get('start_time'),
                    shift_data.get('end_time'),
                    shift_data.get('salary')
                ))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error adding shift: {e}")
            return False

    def get_user_shifts(self, user_id: str) -> List[Dict[str, Any]]:
        """Получение всех смен пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor=conn.execute('''
                    SELECT id, date, role, program, start_time, end_time, salary
                    FROM shifts WHERE user_id = ?
                    ORDER BY date DESC, start_time DESC
                ''', (user_id,))

                shifts=[]
                for row in cursor.fetchall():
                    shift={
                        'id': row[0],
                        'date': datetime.fromisoformat(row[1]).date() if row[1] else None,
                        'role': row[2],
                        'program': row[3],
                        'start_time': row[4],
                        'end_time': row[5],
                        'salary': row[6]
                    }
                    shifts.append(shift)
                return shifts
        except Exception as e:
            print(f"Error getting shifts: {e}")
            return []

    def delete_shift(self, user_id: str, shift_id: int) -> bool:
        """Удаление смены"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor=conn.execute('''
                    DELETE FROM shifts WHERE id = ? AND user_id = ?
                ''', (shift_id, user_id))
                conn.commit()
                return cursor.rowcount>0
        except Exception as e:
            print(f"Error deleting shift: {e}")
            return False

    def update_shift(self, user_id: str, shift_id: int, field: str, value: Any) -> bool:
        """Обновление поля смены"""
        try:
            if field == 'date' and value:
                value=value.isoformat()

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(f'''
                    UPDATE shifts SET {field} = ? WHERE id = ? AND user_id = ?
                ''', (value, shift_id, user_id))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error updating shift: {e}")
            return False

    # ====== СТАТИСТИКА ======

    def get_user_statistics(self, user_id: str) -> Dict:
        """Получение статистики пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            # Общее количество смен
            cursor=conn.execute('''
                SELECT COUNT(*), SUM(salary)
                FROM shifts WHERE user_id = ?
            ''', (user_id,))
            count, total_salary=cursor.fetchone()

            # Статистика по месяцам
            cursor=conn.execute('''
                SELECT strftime('%Y-%m', date) as month, COUNT(*), SUM(salary)
                FROM shifts 
                WHERE user_id = ? AND date IS NOT NULL
                GROUP BY month
                ORDER BY month DESC
                LIMIT 12
            ''', (user_id,))

            monthly_stats=[]
            for row in cursor.fetchall():
                monthly_stats.append({
                    'month': row[0],
                    'count': row[1],
                    'salary': row[2] or 0
                })

            return {
                'total_shifts': count or 0,
                'total_salary': total_salary or 0,
                'monthly_stats': monthly_stats
            }