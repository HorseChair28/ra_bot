from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from db import get_all_shifts, get_statistics
from datetime import datetime

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
        import traceback
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
    print("🌐 Веб-интерфейс: http://localhost:5000")
    print("📡 API: http://localhost:5000/api/shifts")
    app.run(debug=True, host='0.0.0.0', port=8001)