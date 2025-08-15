# run.py - Исправленная версия
import subprocess
import sys
import os
import time
import signal
from threading import Thread, Event
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger=logging.getLogger('main')


class ShiftTrackerRunner:
    def __init__(self):
        self.processes=[]
        self.shutdown_event=Event()

    def start_bot(self):
        """Запуск Telegram бота"""
        logger.info("🤖 Запуск Telegram бота...")
        try:
            process=subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            self.processes.append(('bot', process))

            # Неблокирующее чтение вывода
            while not self.shutdown_event.is_set():
                if process.poll() is not None:
                    logger.warning("🤖 Бот завершился неожиданно")
                    break

                try:
                    line=process.stdout.readline()
                    if line:
                        logger.info(f"[BOT] {line.strip()}")
                except:
                    break
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")

    def start_web(self):
        """Запуск веб-сервера"""
        logger.info("🌐 Запуск веб-сервера...")
        try:
            process=subprocess.Popen(
                [sys.executable, "app.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            self.processes.append(('web', process))

            # Неблокирующее чтение вывода
            while not self.shutdown_event.is_set():
                if process.poll() is not None:
                    logger.warning("🌐 Веб-сервер завершился неожиданно")
                    break

                try:
                    line=process.stdout.readline()
                    if line:
                        logger.info(f"[WEB] {line.strip()}")
                except:
                    break
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Ошибка при запуске веб-сервера: {e}")

    def signal_handler(self, signum, frame):
        """Обработчик сигналов для корректного завершения"""
        logger.info(f"⚠️  Получен сигнал {signum}. Останавливаем сервисы...")
        self.shutdown_event.set()
        self.stop()

    def stop(self):
        """Остановка всех процессов"""
        logger.info("🛑 Начинаем остановку процессов...")

        for name, process in self.processes:
            if process.poll() is None:  # Процесс еще работает
                logger.info(f"Останавливаем {name} (PID: {process.pid})")

                # Сначала пытаемся мягко завершить
                process.terminate()

                try:
                    # Ждем 5 секунд на мягкое завершение
                    process.wait(timeout=5)
                    logger.info(f"✅ {name} корректно завершен")
                except subprocess.TimeoutExpired:
                    # Если не помогло - убиваем принудительно
                    logger.warning(f"⚡ Принудительно завершаем {name}")
                    process.kill()
                    process.wait()

        logger.info("✅ Все процессы остановлены")
        sys.exit(0)

    def monitor_processes(self):
        """Мониторинг процессов"""
        while not self.shutdown_event.is_set():
            dead_processes=[]
            for name, process in self.processes:
                if process.poll() is not None:
                    dead_processes.append((name, process))

            if dead_processes:
                for name, process in dead_processes:
                    logger.error(f"❌ Процесс {name} завершился с кодом {process.returncode}")
                    self.processes.remove((name, process))

                # Если все процессы упали - завершаемся
                if not self.processes:
                    logger.error("💥 Все процессы завершились, останавливаем систему")
                    self.shutdown_event.set()
                    break

            time.sleep(5)  # Проверяем каждые 5 секунд

    def run(self):
        """Главный метод запуска"""
        # Регистрируем обработчики сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        logger.info("=" * 50)
        logger.info("🚀 ЗАПУСК СИСТЕМЫ УЧЕТА СМЕН")
        logger.info("=" * 50)

        # Создаем потоки (НЕ daemon!)
        bot_thread=Thread(target=self.start_bot, name='BotThread')
        web_thread=Thread(target=self.start_web, name='WebThread')
        monitor_thread=Thread(target=self.monitor_processes, name='MonitorThread')

        # Запускаем потоки
        bot_thread.start()
        time.sleep(2)  # Небольшая задержка между запусками
        web_thread.start()
        monitor_thread.start()

        logger.info("✅ Система запущена!")
        logger.info("📱 Telegram бот: работает")
        logger.info("🌐 Веб-интерфейс: работает")
        logger.info("Для остановки отправьте SIGTERM или SIGINT")

        try:
            # Ждем сигнала остановки
            while not self.shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Получен Ctrl+C")
            self.signal_handler(signal.SIGINT, None)
        finally:
            # Убеждаемся, что все остановлено
            if not self.shutdown_event.is_set():
                self.stop()


if __name__ == "__main__":
    runner=ShiftTrackerRunner()
    runner.run()