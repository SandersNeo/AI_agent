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
import ctypes
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
        self._set_text_to_input(edit, self.config.prompt)
        current_value = self._read_input_value(edit)
        if current_value:
            self.logger.info(f"Поле ввода содержит: {current_value[:120]!r}")
        time.sleep(1)
        full_text = self._window_dump_text(self.main_window)
        if self.config.prompt.lower() not in full_text.lower():
            self.logger.info("Текст не отразился в общем dump окна, продолжаем по кнопке отправки.")

    def _send_prompt(self) -> None:
        self.logger.info("Нажимаем 'Отправить'.")
        button = self._find_descendant_by_titles(["Отправить", "Send"], ["Button"], 20)
        self._click(button)
        self._handle_pending_approval()

    def _wait_expected_response(self) -> None:
        self.logger.info("Ждём ожидаемый ответ агента.")
        deadline = time.time() + self.config.timeout_sec
        expected = self.config.expected_text.lower()
        error_markers = ("задача завершена с ошибкой", "ошибка api", "ошибка:")
        while time.time() < deadline:
            self._raise_if_error_dialog()
            self._handle_pending_approval()
            text_dump = self._window_dump_text(self.main_window).lower()
            if expected in text_dump:
                return
            for marker in error_markers:
                if marker in text_dump:
                    raise RuntimeError(f"В форме агента зафиксирована ошибка:\n{text_dump}")
            time.sleep(2)
        raise RuntimeError(f"Не дождались ожидаемого текста ответа: {self.config.expected_text!r}")

    def _handle_pending_approval(self) -> None:
        full_text = self._window_dump_text(self.main_window).lower()
        if "требуется подтверждение действия" not in full_text:
            return
        self.logger.info("Обнаружен pending approval, подтверждаем выполнение.")
        for titles in (
            ["Выполнять без подтверждения", "Execute without confirmation"],
            ["Подтвердить", "Approve"],
        ):
            try:
                button = self._find_descendant_by_titles(titles, ["Button"], 5)
                self._click(button)
                time.sleep(1)
                return
            except Exception:
                continue

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
            if ctype != "Edit":
                continue
            text = self._safe_text(item).strip().lower()
            rect = item.rectangle()
            if rect.width() < 300 or rect.height() < 40:
                continue
            if rect.left < 240 or rect.top < 140 or rect.top > 280:
                continue
            if rect.right > 760:
                continue
            if "search" in text or "текущий диалог" in text or "decision timeline" in text:
                continue
            candidates.append(item)
        if not candidates:
            raise RuntimeError("Не найдено поле ввода сообщения в форме агента.")
        candidates.sort(
            key=lambda item: (
                abs(item.rectangle().top - 170),
                abs(item.rectangle().left - 270),
            )
        )
        return candidates[0]

    def _set_text_to_input(self, control, text: str) -> None:
        self._activate_main_window()
        self._click(control)
        hwnd = self._get_hwnd(control)
        if hwnd:
            self.logger.info(f"Пробуем native hwnd для поля ввода: {hwnd}")
            if self._set_text_via_hwnd(hwnd, text) and self._read_input_value(control):
                return
        if self._set_text_via_rpa(control, text):
            return
        raise RuntimeError("Не удалось ввести текст в поле формы агента.")

    def _read_input_value(self, control) -> str:
        try:
            iface_value = getattr(control, "iface_value", None)
            if iface_value is not None:
                value = iface_value.CurrentValue
                if value is not None:
                    return str(value).strip()
        except Exception:
            pass
        return self._safe_text(control)

    def _get_hwnd(self, control) -> int:
        for attr in ("handle",):
            try:
                value = getattr(control, attr, None)
                if isinstance(value, int) and value:
                    return value
            except Exception:
                pass
        try:
            value = getattr(control.element_info, "handle", 0)
            if isinstance(value, int) and value:
                return value
        except Exception:
            pass
        try:
            rect = control.rectangle()
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            point = POINT(rect.left + max(1, rect.width() // 2), rect.top + max(1, rect.height() // 2))
            value = ctypes.windll.user32.WindowFromPoint(point)
            if isinstance(value, int) and value:
                return value
        except Exception:
            pass
        return 0

    def _set_text_via_hwnd(self, hwnd: int, text: str) -> bool:
        WM_SETTEXT = 0x000C
        EM_SETSEL = 0x00B1
        EM_REPLACESEL = 0x00C2
        WM_CHAR = 0x0102
        try:
            user32 = ctypes.windll.user32
            user32.SetForegroundWindow(self.main_window.handle)
            user32.SendMessageW(hwnd, EM_SETSEL, 0, -1)
            buffer = ctypes.create_unicode_buffer(text)
            result = user32.SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.cast(buffer, ctypes.c_wchar_p))
            if result == 0:
                user32.SendMessageW(hwnd, EM_SETSEL, -1, -1)
                replace_buffer = ctypes.create_unicode_buffer(text)
                user32.SendMessageW(hwnd, EM_REPLACESEL, 1, ctypes.cast(replace_buffer, ctypes.c_wchar_p))
            if not self._safe_text_by_hwnd(hwnd):
                for ch in text:
                    user32.SendMessageW(hwnd, WM_CHAR, ord(ch), 0)
            user32.SendMessageW(hwnd, 0x000F, 0, 0)
            keyboard.send_keys("{TAB}", pause=0.05)
            return True
        except Exception:
            return False

    def _set_text_via_rpa(self, control, text: str) -> bool:
        rect = control.rectangle()
        anchor_points = [
            (rect.left + 18, rect.top + 18),
            (rect.left + max(30, rect.width() // 6), rect.top + max(18, rect.height() // 2)),
            (rect.left + max(40, rect.width() // 3), rect.top + max(18, rect.height() // 2)),
            (rect.left + max(50, rect.width() // 2), rect.top + max(18, rect.height() // 2)),
        ]
        for index, coords in enumerate(anchor_points, start=1):
            try:
                self.logger.info(f"RPA-ввод: попытка {index}, фокус в точку {coords}.")
                self._activate_main_window()
                self._click_at(coords)
                time.sleep(0.2)
                self._double_click_at(coords)
                time.sleep(0.2)
                self._drag_select_input_area(rect)
                time.sleep(0.2)
                self._paste_text_to_active_window(text)
                time.sleep(0.4)
                keyboard.send_keys("{TAB}", pause=0.05)
                time.sleep(0.4)
                if self._read_input_value(control):
                    self.logger.info("RPA-ввод: поле вернуло непустое значение.")
                    return True
                full_text = self._window_dump_text(self.main_window).lower()
                if text.lower() in full_text:
                    self.logger.info("RPA-ввод: текст обнаружен в общем дампе окна.")
                    return True
            except Exception as exc:
                self.logger.info(f"RPA-ввод: попытка {index} завершилась ошибкой: {exc}")
        return False

    def _activate_main_window(self) -> None:
        try:
            self.main_window.set_focus()
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetForegroundWindow(self.main_window.handle)
        except Exception:
            pass
        time.sleep(0.2)

    def _click_at(self, coords: tuple[int, int]) -> None:
        mouse.click(coords=coords)
        time.sleep(0.2)

    def _double_click_at(self, coords: tuple[int, int]) -> None:
        mouse.double_click(coords=coords)
        time.sleep(0.2)

    def _drag_select_input_area(self, rect) -> None:
        y = rect.top + max(18, rect.height() // 2)
        start = (rect.left + max(20, rect.width() // 8), y)
        end = (rect.right - max(20, rect.width() // 8), y)
        self._mouse_drag(start, end)
        keyboard.send_keys("^a", pause=0.05)
        keyboard.send_keys("{BACKSPACE}", pause=0.05)

    def _mouse_drag(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self._set_cursor_pos(*start)
        self._mouse_left_down()
        time.sleep(0.1)
        self._set_cursor_pos(*end)
        time.sleep(0.1)
        self._mouse_left_up()
        time.sleep(0.2)

    def _paste_text_to_active_window(self, text: str) -> None:
        self._set_clipboard_text(text)
        keyboard.send_keys("^v", pause=0.05)
        time.sleep(0.1)
        self._send_input_unicode_text(text)

    def _set_clipboard_text(self, text: str) -> None:
        GMEM_MOVEABLE = 0x0002
        CF_UNICODETEXT = 13
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = ctypes.c_int
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.restype = ctypes.c_void_p
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_int
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = ctypes.c_int
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = ctypes.c_int
        data = (text + "\x00").encode("utf-16le")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise RuntimeError("Не удалось выделить память под буфер обмена.")
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            raise RuntimeError("Не удалось заблокировать память под буфер обмена.")
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.OpenClipboard(0):
            kernel32.GlobalFree(handle)
            raise RuntimeError("Не удалось открыть буфер обмена.")
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                raise RuntimeError("Не удалось записать текст в буфер обмена.")
            handle = None
        finally:
            user32.CloseClipboard()
            if handle:
                kernel32.GlobalFree(handle)

    def _set_cursor_pos(self, x: int, y: int) -> None:
        ctypes.windll.user32.SetCursorPos(x, y)

    def _mouse_left_down(self) -> None:
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)

    def _mouse_left_up(self) -> None:
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)

    def _safe_text_by_hwnd(self, hwnd: int) -> str:
        try:
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value.strip()
        except Exception:
            return ""

    def _send_input_unicode_text(self, text: str) -> None:
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class _INPUTunion(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTunion)]

        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        for ch in text:
            extra = ctypes.c_ulong(0)
            down = INPUT(1, _INPUTunion(ki=KEYBDINPUT(0, ord(ch), KEYEVENTF_UNICODE, 0, ctypes.pointer(extra))))
            up = INPUT(1, _INPUTunion(ki=KEYBDINPUT(0, ord(ch), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))))
            ctypes.windll.user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
            ctypes.windll.user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))

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
                hwnd = self._get_hwnd(item)
                class_name = ""
                try:
                    if hwnd:
                        class_buf = ctypes.create_unicode_buffer(256)
                        ctypes.windll.user32.GetClassNameW(hwnd, class_buf, 255)
                        class_name = class_buf.value
                except Exception:
                    class_name = ""
                chunks.append(
                    f"text={text!r} | type={ctype!r} | hwnd={hwnd!r} | class={class_name!r} | rect=({rect.left},{rect.top},{rect.right},{rect.bottom})"
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
