# run.py - Главный скрипт для запуска всей системы
import subprocess
import sys
import os
import time
import signal
from threading import Thread
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger=logging.getLogger(__name__)


class ShiftTrackerRunner:
    def __init__(self):
        self.processes=[]
        self.running=True

    def start_bot(self):
        """Запуск Telegram бота"""
        logger.info("🤖 Запуск Telegram бота...")
        try:
            process=subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            self.processes.append(process)

            # Читаем вывод бота
            for line in iter(process.stdout.readline, ''):
                if line and self.running:
                    print(f"[BOT] {line.strip()}")

        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")

    def start_web(self):
        """Запуск веб-сервера"""
        logger.info("🌐 Запуск веб-сервера...")
        try:
            process=subprocess.Popen(
                [sys.executable, "app.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            self.processes.append(process)

            # Читаем вывод веб-сервера
            for line in iter(process.stdout.readline, ''):
                if line and self.running:
                    print(f"[WEB] {line.strip()}")

        except Exception as e:
            logger.error(f"Ошибка при запуске веб-сервера: {e}")

    def signal_handler(self, signum, frame):
        """Обработчик сигналов для корректного завершения"""
        logger.info("\n⚠️  Получен сигнал завершения. Останавливаем сервисы...")
        self.running=False
        self.stop()

    def stop(self):
        """Остановка всех процессов"""
        for process in self.processes:
            if process.poll() is None:  # Проверяем, что процесс еще работает
                logger.info(f"Останавливаем процесс PID: {process.pid}")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

        logger.info("✅ Все процессы остановлены")

    def run(self):
        """Главный метод запуска"""
        # Регистрируем обработчики сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        print("=" * 50)
        print("🚀 ЗАПУСК СИСТЕМЫ УЧЕТА СМЕН")
        print("=" * 50)

        # Создаем потоки для запуска процессов
        bot_thread=Thread(target=self.start_bot, daemon=True)
        web_thread=Thread(target=self.start_web, daemon=True)

        # Запускаем потоки
        bot_thread.start()
        time.sleep(2)  # Небольшая задержка между запусками
        web_thread.start()

        print("\n✅ Система запущена!")
        print("📱 Telegram бот: работает")
        print("🌐 Веб-интерфейс: http://localhost:5000")
        print("\nДля остановки нажмите Ctrl+C\n")
        print("-" * 50)

        try:
            # Ждем завершения потоков
            bot_thread.join()
            web_thread.join()
        except KeyboardInterrupt:
            pass
        finally:
            if self.running:
                self.stop()


if __name__ == "__main__":
    runner=ShiftTrackerRunner()
    runner.run()

# ============================================
# run_simple.py - Упрощенная версия
# ============================================

# !/usr/bin/env python3
"""
Простой скрипт для запуска бота и веб-сервера
Использование: python run_simple.py
"""

import subprocess
import os
import sys
import time


def run():
    print("🚀 Запуск системы учета смен...")
    print("-" * 40)

    # Запускаем бота в фоне
    print("▶️  Запуск Telegram бота...")
    bot_process=subprocess.Popen([sys.executable, "bot.py"])
    time.sleep(2)

    # Запускаем веб-сервер в фоне
    print("▶️  Запуск веб-сервера...")
    web_process=subprocess.Popen([sys.executable, "app.py"])

    print("-" * 40)
    print("✅ Система запущена!")
    print("🌐 Веб-интерфейс: http://localhost:5000")
    print("\n⚠️  Для остановки нажмите Ctrl+C")

    try:
        # Ждем завершения
        bot_process.wait()
        web_process.wait()
    except KeyboardInterrupt:
        print("\n\n🛑 Остановка системы...")
        bot_process.terminate()
        web_process.terminate()
        print("✅ Система остановлена")
        sys.exit(0)


if __name__ == "__main__":
    run()


