# -*- coding: utf-8 -*-
"""
Desktop UI тест формы ИИ агента без Vanessa и без COM.

Сценарий:
1. Открыть клиент 1С.
2. Открыть именно форму "ИИ Агент".
3. Нажать "Новый диалог".
4. Ввести пользовательское сообщение в поле ввода.
5. Нажать кнопку "Отправить".
6. Дождаться ожидаемого текста в чате или статусе.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def setup_console_encoding() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleCP(65001)
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


try:
    from pywinauto import Application, Desktop, keyboard, mouse
except Exception:
    print(
        "Ошибка: не импортирован pywinauto. Установите зависимости:\n"
        "pip install -r automation\\ui\\requirements-ui.txt",
        file=sys.stderr,
    )
    raise


@dataclass
class UiConfig:
    platform_exe: str
    base_path: str
    user: str
    prompt: str
    expected_text: str
    timeout_sec: int
    startup_timeout_sec: int
    backend: str
    log_file: Optional[str]
    screenshot_dir: Optional[str]
    leave_open: bool


class Logger:
    def __init__(self, log_file: Optional[str]) -> None:
        self._path = Path(log_file) if log_file else None
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, message: str) -> None:
        line = f"[INFO] {message}"
        print(line)
        if self._path:
            with self._path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def error(self, message: str) -> None:
        line = f"[ERROR] {message}"
        print(line, file=sys.stderr)
        if self._path:
            with self._path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")


class OneCAgentUiTest:
    def __init__(self, config: UiConfig, logger: Logger) -> None:
        self.config = config
        self.logger = logger
        self.process: Optional[subprocess.Popen[str]] = None
        self.app: Optional[Application] = None
        self.main_window = None

    def run(self) -> int:
        try:
            self._start_client()
            self._open_agent_form()
            self._start_new_dialog()
            self._enter_prompt()
            self._send_prompt()
            self._wait_expected_response()
            self.logger.info("UI тест завершён успешно.")
            return 0
        except Exception as exc:
            self.logger.error(str(exc))
            self._capture_debug_artifacts()
            return 1
        finally:
            if not self.config.leave_open:
                self._close_client()

    def _start_client(self) -> None:
        client_env = os.environ.copy()
        self._clear_proxy_env(client_env)
        cmd = [
            self.config.platform_exe,
            "ENTERPRISE",
            "/DisableStartupDialogs",
            "/DisableStartupMessages",
            "/F",
            self.config.base_path,
            "/N",
            self.config.user,
        ]
        self.logger.info("Запуск клиента 1С.")
        self.process = subprocess.Popen(cmd, env=client_env)
        self.app = Application(backend=self.config.backend).connect(
            process=self.process.pid,
            timeout=self.config.startup_timeout_sec,
        )
        self.main_window = self._wait_for_top_window()
        self.main_window.set_focus()
        self.logger.info(f"Подключились к окну: {self.main_window.window_text()!r}")

    def _wait_for_top_window(self):
        deadline = time.time() + self.config.startup_timeout_sec
        while time.time() < deadline:
            windows = self.app.windows() if self.app else []
            visible = [w for w in windows if self._safe_is_visible(w)]
            if visible:
                visible.sort(key=lambda w: len(self._safe_text(w)), reverse=True)
                return visible[0]
            self._raise_if_error_dialog()
            time.sleep(1)
        raise RuntimeError("Не удалось дождаться главного окна 1С.")

    def _open_agent_form(self) -> None:
        self.logger.info("Открываем раздел 'ИИ Агент'.")
        self._wait_until_client_ready(60)
        nav_item = self._find_descendant_exact("ИИ Агент", "TabItem", 20)
        self._open_agent_section(nav_item)
        if self._window_contains_any(["Текущий диалог", "Новый диалог", "Отправить"]):
            self.logger.info("Форма агента уже открыта.")
            return
        agent_entry = self._find_descendant_by_titles(
            ["ИИ Агент"],
            ["MenuItem", "Hyperlink", "Text", "ListItem"],
            20,
        )
        self._click(agent_entry)
        self._wait_agent_form_ready(30)
        self.logger.info("Форма агента открыта.")

    def _start_new_dialog(self) -> None:
        self.logger.info("Создаём новый диалог в форме агента.")
        button = self._find_descendant_by_titles(["Новый диалог", "New dialog"], ["Button"], 20)
        self._click(button)
        self._wait_window_text_contains("Готов к работе", 20)

    def _enter_prompt(self) -> None:
        self.logger.info("Вводим пользовательское сообщение.")
        edit = self._locate_prompt_input()
        self._click(edit)
        keyboard.send_keys("^a{BACKSPACE}", pause=0.05)
        keyboard.send_keys(self._escape_for_send_keys(self.config.prompt), with_spaces=True, pause=0.02)
        time.sleep(1)
        full_text = self._window_dump_text(self.main_window)
        if self.config.prompt.lower() not in full_text.lower():
            self.logger.info("Текст не отразился в общем dump окна, продолжаем по кнопке отправки.")

    def _send_prompt(self) -> None:
        self.logger.info("Нажимаем 'Отправить'.")
        button = self._find_descendant_by_titles(["Отправить", "Send"], ["Button"], 20)
        self._click(button)

    def _wait_expected_response(self) -> None:
        self.logger.info("Ждём ожидаемый ответ агента.")
        deadline = time.time() + self.config.timeout_sec
        expected = self.config.expected_text.lower()
        error_markers = ("задача завершена с ошибкой", "ошибка api", "ошибка:")
        while time.time() < deadline:
            self._raise_if_error_dialog()
            text_dump = self._window_dump_text(self.main_window).lower()
            if expected in text_dump:
                return
            for marker in error_markers:
                if marker in text_dump:
                    raise RuntimeError(f"В форме агента зафиксирована ошибка:\n{text_dump}")
            time.sleep(2)
        raise RuntimeError(f"Не дождались ожидаемого текста ответа: {self.config.expected_text!r}")

    def _find_descendant_by_titles(self, titles: list[str], control_types: list[str], timeout: int):
        deadline = time.time() + timeout
        wanted = {title.lower() for title in titles}
        allowed_types = set(control_types)
        while time.time() < deadline:
            self._raise_if_error_dialog()
            for item in self._iter_descendants():
                text = self._safe_text(item).lower()
                ctype = self._safe_control_type(item)
                if text in wanted and ctype in allowed_types:
                    return item
            time.sleep(1)
        raise RuntimeError(f"Не найден элемент {titles!r} ({', '.join(control_types)}).")

    def _open_agent_section(self, nav_item) -> None:
        rect = nav_item.rectangle()
        y = rect.top + max(1, rect.height() // 2)
        x_points = [
            rect.left + max(1, rect.width() // 2),
            rect.left + 50,
            rect.right - 50,
        ]
        for x in x_points:
            self.main_window.set_focus()
            mouse.click(coords=(x, y))
            time.sleep(2)
            try:
                if self._window_contains_any(["Диалоги", "Настройки пользователей", "Текущий диалог"]):
                    return
                self._find_descendant_by_titles(
                    ["ИИ Агент", "Диалоги", "Настройки пользователей"],
                    ["MenuItem", "Hyperlink", "Text", "ListItem"],
                    2,
                )
                return
            except Exception:
                continue
        raise RuntimeError("Не удалось раскрыть раздел 'ИИ Агент'.")

    def _wait_until_client_ready(self, timeout: int) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_error_dialog()
            text_dump = self._window_dump_text(self.main_window)
            if "Выполняется расчет..." not in text_dump:
                return
            time.sleep(2)
        self.logger.info("Стартовая страница всё ещё занята, продолжаем попытку навигации.")

    def _find_descendant_exact(self, title: str, control_type: str, timeout: int):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_error_dialog()
            for item in self._iter_descendants():
                if self._safe_text(item) == title and self._safe_control_type(item) == control_type:
                    return item
            time.sleep(1)
        raise RuntimeError(f"Не найден элемент '{title}' ({control_type}).")

    def _wait_window_text_contains(self, text: str, timeout: int) -> None:
        deadline = time.time() + timeout
        needle = text.lower()
        while time.time() < deadline:
            self._raise_if_error_dialog()
            full_text = self._window_dump_text(self.main_window).lower()
            if needle in full_text:
                return
            time.sleep(1)
        raise RuntimeError(f"Не найден текст в окне: {text!r}")

    def _wait_agent_form_ready(self, timeout: int) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_error_dialog()
            if self._window_contains_any(["Текущий диалог", "Новый диалог", "Отправить"]):
                return
            time.sleep(1)
        raise RuntimeError("Не удалось дождаться загрузки формы агента.")

    def _window_contains_any(self, texts: list[str]) -> bool:
        full_text = self._window_dump_text(self.main_window).lower()
        return any(text.lower() in full_text for text in texts)

    def _locate_prompt_input(self):
        candidates = []
        for item in self._iter_descendants():
            ctype = self._safe_control_type(item)
            if ctype not in ("Edit", "Document", "Pane"):
                continue
            text = self._safe_text(item).strip().lower()
            rect = item.rectangle()
            if rect.width() < 300 or rect.height() < 40:
                continue
            if "текущий диалог" in text or "decision timeline" in text:
                continue
            candidates.append(item)
        if not candidates:
            raise RuntimeError("Не найдено поле ввода сообщения в форме агента.")
        candidates.sort(
            key=lambda item: (
                item.rectangle().top,
                -item.rectangle().width(),
            )
        )
        return candidates[0]

    def _raise_if_error_dialog(self) -> None:
        for win in Desktop(backend=self.config.backend).windows():
            try:
                if self.process is not None and win.process_id() != self.process.pid:
                    continue
                if not self._safe_is_visible(win):
                    continue
                text_dump = self._window_dump_text(win)
                if "Сформировать отчет об ошибке" in text_dump or "не определена" in text_dump.lower():
                    self._try_close_error_dialog(win)
                    raise RuntimeError(f"1С показала модальную ошибку:\n{text_dump.strip()}")
            except RuntimeError:
                raise
            except Exception:
                continue

    def _try_close_error_dialog(self, window) -> None:
        for item in self._iter_descendants(window):
            if self._safe_text(item) == "OK" and self._safe_control_type(item) == "Button":
                try:
                    self._click(item)
                except Exception:
                    pass
                return

    def _click(self, control) -> None:
        rect = control.rectangle()
        coords = (rect.left + max(1, rect.width() // 2), rect.top + max(1, rect.height() // 2))
        mouse.click(coords=coords)
        time.sleep(1)

    def _double_click(self, control) -> None:
        rect = control.rectangle()
        coords = (rect.left + max(1, rect.width() // 2), rect.top + max(1, rect.height() // 2))
        mouse.double_click(coords=coords)
        time.sleep(1.5)

    def _iter_descendants(self, window=None):
        if window is None:
            window = self.main_window
        if window is None:
            return []
        try:
            items = window.descendants()
        except Exception:
            return []
        result = []
        for item in items:
            try:
                _ = item.element_info.control_type
                result.append(item)
            except Exception:
                continue
        return result

    def _safe_text(self, control) -> str:
        try:
            return (control.window_text() or "").strip()
        except Exception:
            return ""

    def _safe_control_type(self, control) -> str:
        try:
            return control.element_info.control_type or ""
        except Exception:
            return ""

    def _safe_is_visible(self, control) -> bool:
        try:
            return bool(control.is_visible())
        except Exception:
            return False

    def _window_dump_text(self, window) -> str:
        chunks: list[str] = []
        for item in self._iter_descendants(window):
            text = self._safe_text(item)
            if text:
                chunks.append(text)
        return "\n".join(chunks)

    def _window_dump_controls(self, window) -> str:
        chunks: list[str] = []
        for item in self._iter_descendants(window):
            try:
                text = self._safe_text(item)
                ctype = self._safe_control_type(item)
                rect = item.rectangle()
                chunks.append(
                    f"text={text!r} | type={ctype!r} | rect=({rect.left},{rect.top},{rect.right},{rect.bottom})"
                )
            except Exception:
                continue
        return "\n".join(chunks)

    def _capture_debug_artifacts(self) -> None:
        if not self.config.screenshot_dir or self.main_window is None:
            return
        target_dir = Path(self.config.screenshot_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time())
        dump_path = target_dir / f"ui_failure_{stamp}.txt"
        controls_path = target_dir / f"ui_failure_controls_{stamp}.txt"
        try:
            self.main_window.capture_as_image().save(target_dir / f"ui_failure_{stamp}.png")
            self.logger.info(f"Сохранён скриншот: {target_dir / f'ui_failure_{stamp}.png'}")
        except Exception as exc:
            self.logger.error(f"Не удалось сохранить скриншот: {exc}")
        try:
            dump_path.write_text(self._window_dump_text(self.main_window), encoding="utf-8")
            self.logger.info(f"Сохранён dump окна: {dump_path}")
        except Exception as exc:
            self.logger.error(f"Не удалось сохранить dump окна: {exc}")
        try:
            controls_path.write_text(self._window_dump_controls(self.main_window), encoding="utf-8")
            self.logger.info(f"Сохранён dump контролов окна: {controls_path}")
        except Exception as exc:
            self.logger.error(f"Не удалось сохранить dump контролов окна: {exc}")

    def _close_client(self) -> None:
        self.logger.info("Закрываем клиент 1С.")
        if not self.process:
            return
        try:
            if self.main_window is not None:
                self.main_window.close()
                time.sleep(2)
        except Exception:
            pass
        try:
            self.process.terminate()
            self.process.wait(timeout=15)
        except Exception:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Stop-Process -Id {self.process.pid} -Force -ErrorAction SilentlyContinue",
                ],
                check=False,
                timeout=15,
            )

    @staticmethod
    def _escape_for_send_keys(text: str) -> str:
        for old, new in (
            ("{", "{{}"),
            ("}", "{}}"),
            ("+", "{+}"),
            ("^", "{^}"),
            ("%", "{%}"),
            ("~", "{~}"),
            ("(", "{(}"),
            (")", "{)}"),
            ("[", "{[}"),
            ("]", "{]}"),
        ):
            text = text.replace(old, new)
        return text

    @staticmethod
    def _clear_proxy_env(env: dict[str, str]) -> None:
        if env.get("AI_AGENT_KEEP_PROXY_ENV") == "1":
            return
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
        ):
            env.pop(name, None)


def parse_args() -> UiConfig:
    parser = argparse.ArgumentParser(
        description="Desktop UI тест формы ИИ агента без Vanessa и без COM"
    )
    parser.add_argument(
        "--platform-exe",
        default=r"C:\Program Files\1cv8\8.5.1.1150\bin\1cv8.exe",
        help="Путь к 1cv8.exe",
    )
    parser.add_argument(
        "--base-path",
        default=r"D:\bd\УНФ3013238",
        help="Путь к файловой базе 1С",
    )
    parser.add_argument(
        "--user",
        default="Администратор",
        help="Пользователь 1С",
    )
    parser.add_argument(
        "--prompt",
        default="какие поля есть у справочника Контрагенты",
        help="Текст сообщения агенту",
    )
    parser.add_argument(
        "--expected-text",
        default="Поля успешно получены",
        help="Ожидаемый фрагмент ответа",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=180,
        help="Таймаут ожидания ответа",
    )
    parser.add_argument(
        "--startup-timeout-sec",
        type=int,
        default=90,
        help="Таймаут старта клиента",
    )
    parser.add_argument(
        "--backend",
        default="uia",
        choices=["uia", "win32"],
        help="Backend pywinauto",
    )
    parser.add_argument(
        "--log-file",
        default=str(Path("automation") / "logs" / "ui_pywinauto.log"),
        help="Файл лога",
    )
    parser.add_argument(
        "--screenshot-dir",
        default=str(Path("automation") / "logs" / "ui_artifacts"),
        help="Каталог для артефактов при падении",
    )
    parser.add_argument(
        "--leave-open",
        action="store_true",
        help="Не закрывать 1С после теста",
    )
    args = parser.parse_args()
    return UiConfig(
        platform_exe=args.platform_exe,
        base_path=args.base_path,
        user=args.user,
        prompt=args.prompt,
        expected_text=args.expected_text,
        timeout_sec=args.timeout_sec,
        startup_timeout_sec=args.startup_timeout_sec,
        backend=args.backend,
        log_file=args.log_file,
        screenshot_dir=args.screenshot_dir,
        leave_open=args.leave_open,
    )


def main() -> int:
    setup_console_encoding()
    config = parse_args()
    logger = Logger(config.log_file)
    runner = OneCAgentUiTest(config, logger)
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
