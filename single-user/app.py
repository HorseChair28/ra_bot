from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from datetime import datetime
import traceback
import sqlite3
import os

# Определяем пути
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'shifts.db')

# Функции для работы с БД (вместо импорта из db.py)
def get_all_shifts():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute('''
        SELECT * FROM shifts 
        ORDER BY date DESC, start_time DESC
    ''')
    shifts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return shifts

def get_statistics():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute('''
        SELECT COUNT(*) as total, SUM(salary) as total_salary 
        FROM shifts
    ''')
    stats = dict(cursor.fetchone())
    conn.close()
    return stats

def update_shift(user_id, shift_id, field, value):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f'''
            UPDATE shifts SET {field} = ? 
            WHERE id = ? AND user_id = ?
        ''', (value, shift_id, user_id))
        conn.commit()
        affected = conn.total_changes
        conn.close()
        return affected > 0
    except Exception as e:
        print(f"Ошибка обновления: {e}")
        return False

def delete_shift(user_id, shift_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''
            DELETE FROM shifts 
            WHERE id = ? AND user_id = ?
        ''', (shift_id, user_id))
        conn.commit()
        affected = conn.total_changes
        conn.close()
        return affected > 0
    except Exception as e:
        print(f"Ошибка удаления: {e}")
        return False


app=Flask(__name__)
CORS(app)  # Разрешаем CORS для API


@app.route("/")
def index():
    """Главная страница с веб-интерфейсом"""
    return render_template("index.html")


@app.route("/api/shifts")
def api_shifts():
    """API endpoint для получения смен"""
    try:
        print("[DEBUG] API /api/shifts вызван")
        month=request.args.get("month", type=int)
        user_id=request.args.get("user_id")

        shifts=get_all_shifts()
        print(f"[DEBUG] Получено смен: {len(shifts)}")

        # Фильтрация по месяцу
        if month:
            shifts=[s for s in shifts if s.get("date") and
                    datetime.fromisoformat(s["date"]).month == month]

        # Фильтрация по пользователю
        if user_id:
            shifts=[s for s in shifts if s.get("user_id") == user_id]

        # Конвертируем date объекты в строки для JSON
        for shift in shifts:
            if shift.get('date') and hasattr(shift['date'], 'isoformat'):
                shift['date']=shift['date'].isoformat()

        return jsonify(shifts)

    except Exception as e:
        print(f"[ERROR] Ошибка в API: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/shifts/<int:shift_id>", methods=['PUT'])
def api_update_shift(shift_id):
    """API endpoint для обновления смены"""
    try:
        print(f"[DEBUG] Обновление смены ID {shift_id}")
        data=request.get_json()

        if not data:
            return jsonify({"error": "Нет данных для обновления"}), 400

        # Получаем user_id из данных смены (в реальном приложении лучше из авторизации)
        user_id=data.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id обязателен"}), 400

        # Обновляем каждое поле отдельно
        updated_fields=[]

        for field in ['date', 'role', 'program', 'start_time', 'end_time', 'salary']:
            if field in data:
                value=data[field]

                # Обработка пустых значений
                if value == '' or value == 'null':
                    value=None

                # Валидация даты
                if field == 'date' and value:
                    try:
                        # Проверяем формат даты
                        parsed_date=datetime.fromisoformat(value)
                        print(f"[DEBUG] Дата валидна: {value} -> {parsed_date}")
                    except ValueError as e:
                        print(f"[ERROR] Неверный формат даты: {value}, ошибка: {e}")
                        return jsonify({"error": f"Неверный формат даты: {value}"}), 400

                # Валидация времени
                if field in ['start_time', 'end_time'] and value:
                    try:
                        datetime.strptime(value, '%H:%M')
                    except ValueError:
                        return jsonify({"error": f"Неверный формат времени: {value}"}), 400

                # Валидация зарплаты
                if field == 'salary' and value is not None:
                    try:
                        value=int(value)
                        if value<0:
                            return jsonify({"error": "Зарплата не может быть отрицательной"}), 400
                    except (ValueError, TypeError):
                        return jsonify({"error": f"Неверный формат зарплаты: {value}"}), 400

                # Обновляем поле в базе
                print(f"[DEBUG] Обновляем поле {field} = {value} (тип: {type(value)})")
                if update_shift(user_id, shift_id, field, value):
                    updated_fields.append(field)
                    print(f"[DEBUG] Успешно обновлено поле {field}")
                else:
                    print(f"[ERROR] Ошибка обновления поля {field}")
                    return jsonify({"error": f"Ошибка обновления поля {field}"}), 500

        if updated_fields:
            print(f"[SUCCESS] Смена {shift_id} обновлена. Поля: {updated_fields}")
            return jsonify({
                "success": True,
                "message": f"Смена обновлена",
                "updated_fields": updated_fields
            })
        else:
            return jsonify({"success": True, "message": "Нет изменений"})

    except Exception as e:
        print(f"[ERROR] Ошибка при обновлении смены: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/shifts/<int:shift_id>", methods=['DELETE'])
def api_delete_shift(shift_id):
    """API endpoint для удаления смены"""
    try:
        print(f"[DEBUG] Удаление смены ID {shift_id}")

        # В реальном приложении user_id должен браться из авторизации
        # Пока получаем из параметров запроса
        user_id=request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id обязателен"}), 400

        if delete_shift(user_id, shift_id):
            print(f"[SUCCESS] Смена {shift_id} удалена")
            return jsonify({"success": True, "message": "Смена удалена"})
        else:
            print(f"[ERROR] Смена {shift_id} не найдена или не принадлежит пользователю")
            return jsonify({"error": "Смена не найдена или у вас нет прав на её удаление"}), 404

    except Exception as e:
        print(f"[ERROR] Ошибка при удалении смены: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/statistics")
def api_statistics():
    """API endpoint для статистики"""
    try:
        stats=get_statistics()
        return jsonify(stats)
    except Exception as e:
        print(f"[ERROR] Ошибка в статистике: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    """Проверка работоспособности"""
    try:
        shifts_count=len(get_all_shifts())
        return jsonify({
            "status": "healthy",
            "shifts_count": shifts_count,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


if __name__ == "__main__":
    print("🚀 Запуск Flask сервера...")
    print("🌐 Веб-интерфейс: http://localhost:8000")
    print("📡 API: http://localhost:8000/api/shifts")
    print("📝 Новые endpoints:")
    print("   PUT /api/shifts/<id> - обновить смену")
    print("   DELETE /api/shifts/<id> - удалить смену")
    app.run(debug=True, host='0.0.0.0', port=8000)