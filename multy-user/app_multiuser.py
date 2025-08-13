# app_multiuser.py - Flask приложение с авторизацией
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response
from flask_cors import CORS
from database import MultiUserDatabase
from datetime import datetime, date, timedelta
import secrets
import os

from functools import wraps
from flask import request, jsonify, session

import os, secrets
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)

def api_auth_required(f):
    """Авторизация для API: по Bearer api_token ИЛИ по сессии (session_id)."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = None

        # 1) Пробуем Bearer-токен или ?api_token=...
        auth = request.headers.get('Authorization') or ''
        api_token = auth[7:] if auth.startswith('Bearer ') else request.args.get('api_token')
        if api_token:
            user = db.get_user_by_api_token(api_token)

        # 2) Если токена нет/невалиден — пробуем сессию
        if not user:
            sid = session.get('session_id')
            if sid:
                user = db.get_user_by_session(sid)

        if not user:
            return jsonify({'error': 'Unauthorized'}), 401

        request.current_user = user
        return f(*args, **kwargs)
    return decorated_function

app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY', secrets.token_hex(32))
CORS(app)

DB_PATH = os.getenv("DATABASE_PATH", "shifts.db")
db = MultiUserDatabase(DB_PATH)

# ====== ДЕКОРАТОРЫ ДЛЯ ПРОВЕРКИ АВТОРИЗАЦИИ ======

def login_required(f):
    """Декоратор для проверки авторизации через сессию"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Проверяем сессию
        session_id=session.get('session_id')
        if not session_id:
            return redirect(url_for('login'))

        user=db.get_user_by_session(session_id)
        if not user:
            session.clear()
            return redirect(url_for('login'))

        # Добавляем пользователя в контекст
        request.current_user=user
        return f(*args, **kwargs)

    return decorated_function



# ====== СТРАНИЦЫ АВТОРИЗАЦИИ ======

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    if request.method == 'POST':
        data=request.get_json() if request.is_json else request.form

        # Вход по API токену (для пользователей из Telegram)
        if 'api_token' in data:
            user=db.get_user_by_api_token(data['api_token'])
            if user:
                # Создаем сессию
                session_id=db.create_session(user['user_id'])
                session['session_id']=session_id

                if request.is_json:
                    return jsonify({'success': True, 'user': user})
                return redirect(url_for('index'))

        # Вход по email/паролю (для веб-пользователей)
        elif 'email' in data and 'password' in data:
            user_id=db.authenticate_web_user(data['email'], data['password'])
            if user_id:
                # Создаем сессию
                session_id=db.create_session(user_id)
                session['session_id']=session_id

                if request.is_json:
                    return jsonify({'success': True})
                return redirect(url_for('index'))

        if request.is_json:
            return jsonify({'error': 'Invalid credentials'}), 401
        return render_template('login.html', error='Неверные данные для входа')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация нового пользователя"""
    if request.method == 'POST':
        data=request.get_json() if request.is_json else request.form

        email=data.get('email')
        password=data.get('password')
        full_name=data.get('full_name')

        if not email or not password:
            error='Email и пароль обязательны'
            if request.is_json:
                return jsonify({'error': error}), 400
            return render_template('register.html', error=error)

        # Создаем пользователя
        user_id=db.create_user_from_web(email, password, full_name)

        if user_id:
            # Автоматически входим
            session_id=db.create_session(user_id)
            session['session_id']=session_id

            if request.is_json:
                return jsonify({'success': True})
            return redirect(url_for('index'))
        else:
            error='Email уже зарегистрирован'
            if request.is_json:
                return jsonify({'error': error}), 400
            return render_template('register.html', error=error)

    return render_template('register.html')


@app.route('/logout')
def logout():
    """Выход из системы"""
    session_id=session.get('session_id')
    if session_id:
        db.delete_session(session_id)
    session.clear()
    return redirect(url_for('login'))


# ====== ОСНОВНЫЕ СТРАНИЦЫ ======

@app.route('/')
@login_required
def index():
    """Главная страница с календарем"""
    user=request.current_user
    return render_template('index.html', user=user, api_token=user['api_token'])


@app.route('/profile')
@login_required
def profile():
    """Страница профиля"""
    user=request.current_user
    stats=db.get_user_statistics(user['user_id'])
    return render_template('profile.html', user=user, stats=stats)


# ====== API ENDPOINTS ======

@app.route('/api/shifts', methods=['GET'])
@api_auth_required
def api_get_shifts():
    """Получение всех смен пользователя"""
    user=request.current_user
    shifts=db.get_user_shifts(user['user_id'])

    # Преобразуем даты в строки для JSON
    for shift in shifts:
        if shift['date']:
            shift['date']=shift['date'].isoformat()

    return jsonify(shifts)


@app.route('/api/shifts', methods=['POST'])
@api_auth_required
def api_add_shift():
    """Добавление новой смены"""
    user=request.current_user
    data=request.get_json()

    # Преобразуем дату из строки
    if data.get('date'):
        data['date']=datetime.fromisoformat(data['date']).date()

    success=db.add_shift(user['user_id'], data)

    if success:
        return jsonify({'success': True, 'message': 'Смена добавлена'})
    else:
        return jsonify({'success': False, 'error': 'Ошибка при добавлении'}), 400


@app.route('/api/shifts/<int:shift_id>', methods=['PUT'])
@api_auth_required
def api_update_shift(shift_id):
    """Обновление смены"""
    user=request.current_user
    data=request.get_json()

    for field, value in data.items():
        if field == 'date' and value:
            value=datetime.fromisoformat(value).date()

        success=db.update_shift(user['user_id'], shift_id, field, value)
        if not success:
            return jsonify({'error': f'Ошибка при обновлении поля {field}'}), 400

    return jsonify({'success': True})


@app.route('/api/shifts/<int:shift_id>', methods=['DELETE'])
@api_auth_required
def api_delete_shift(shift_id):
    """Удаление смены"""
    user=request.current_user
    success=db.delete_shift(user['user_id'], shift_id)

    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Смена не найдена'}), 404


@app.route('/api/statistics')
@api_auth_required
def api_statistics():
    """Получение статистики"""
    user=request.current_user
    stats=db.get_user_statistics(user['user_id'])
    return jsonify(stats)


@app.route('/api/user')
@api_auth_required
def api_user_info():
    """Информация о текущем пользователе"""
    user=request.current_user
    return jsonify({
        'user_id': user['user_id'],
        'username': user.get('username'),
        'full_name': user.get('full_name'),
        'email': user.get('email')
    })

@app.route('/health')
def health():
    return jsonify({'ok': True})

# ====== ПУБЛИЧНОЕ API ДЛЯ ИНТЕГРАЦИЙ ======

@app.route('/api/public/calendar/<api_token>')
def public_calendar(api_token):
    """Публичный календарь по API токену (для виджетов)"""
    user=db.get_user_by_api_token(api_token)
    if not user:
        return jsonify({'error': 'Invalid token'}), 401

    shifts=db.get_user_shifts(user['user_id'])

    # Форматируем для календаря
    events=[]
    for shift in shifts:
        if shift['date']:
            event={
                'date': shift['date'].isoformat(),
                'title': shift.get('program', 'Смена'),
                'role': shift.get('role'),
                'time': f"{shift.get('start_time', '')}-{shift.get('end_time', '')}",
                'salary': shift.get('salary')
            }
            events.append(event)

    return jsonify(events)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8008)