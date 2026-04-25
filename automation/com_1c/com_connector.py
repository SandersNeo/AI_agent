# -*- coding: utf-8 -*-
"""
Модуль для работы с базой данных 1С через COM.

Содержит:
- выбор COM-коннектора (**V83** → **V85** → **V82**): для сервера 8.3 клиент 8.5 по COM
  даёт несовместимость версий, поэтому сначала пробуем 8.3;
- строка подключения: **файловая** ``File="…";`` или **серверная**
  ``Srvr="…";Ref="…";Usr="…";Pwd="…";`` (целиком в ``1C_CONNECTION_STRING``);
- для **V83**, если у ``Dispatch`` нет метода ``Connect``, подключение через **typelib**
  ``comcntr.dll`` + ``dynamic.Dispatch(..., typeinfo=…)``;
- выполнение запросов и безопасная работа с COM-объектами.

Важно:
- для 1С COM automation программная лицензия может зависеть от Windows-user context;
- sandbox/изолированный пользователь может не видеть ту же 1С-лицензию, что интерактивный пользователь;
- поэтому боевые COM-прогоны 1С на этой машине нужно выполнять вне sandbox-контекста.
"""

import os
import re
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


def setup_console_encoding():
    """Настраивает кодировку stdout/stderr для корректного вывода кириллицы в Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Переключаем консоль на UTF-8 (65001)
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import win32com.client
except ImportError:
    win32com = None  # type: ignore

DEFAULT_COM_PROGIDS: Tuple[str, ...] = (
    "V83.COMConnector",
    "V85.COMConnector",
    "V82.COMConnector",
)

_COMCNTR_TLB_GUID = "{98AC3B5B-5323-418F-8F07-E32F231D2393}"
_IID_IV8_COM_CONNECTOR3 = "{2FF2245E-C604-45BD-AC16-19B1F64BD9A4}"

_verbose = False


def set_verbose(value: bool) -> None:
    """Включить/выключить вывод отладочных сообщений."""
    global _verbose
    _verbose = value


def _log(msg: str) -> None:
    if _verbose:
        print(msg)


def disable_proxy_env_for_1c() -> None:
    """
    Убирает proxy-переменные из окружения текущего процесса перед COM/1C вызовами.

    Это нужно для машин, где shell-сессия запускается с временным SOCKS/HTTP proxy,
    но 1С и провайдер внутри 1С должны ходить напрямую. Поведение можно отключить
    через AI_AGENT_KEEP_PROXY_ENV=1.
    """
    if os.environ.get("AI_AGENT_KEEP_PROXY_ENV") == "1":
        _log("Proxy env сохранены: AI_AGENT_KEEP_PROXY_ENV=1")
        return

    proxy_names = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    removed = []
    for name in proxy_names:
        if os.environ.get(name):
            removed.append(f"{name}={os.environ.get(name)}")
            os.environ.pop(name, None)

    # NO_PROXY без самих proxy-переменных не нужен и только путает диагностику.
    for name in ("NO_PROXY", "no_proxy"):
        if os.environ.get(name):
            removed.append(f"{name}={os.environ.get(name)}")
            os.environ.pop(name, None)

    if removed:
        _log("Proxy env отключены для 1C automation: " + "; ".join(removed))


def call_if_callable(value, *args, **kwargs):
    """Вызывает объект, если он вызваемый, иначе возвращает как есть."""
    if value is None:
        return None
    if win32com and isinstance(value, win32com.client.CDispatch):
        return value
    if callable(value):
        try:
            return value(*args, **kwargs)
        except Exception:
            return None
    return value


def safe_getattr(obj, attr_name: str, default=None):
    """Безопасно получает атрибут COM-объекта."""
    if obj is None:
        return default
    try:
        return getattr(obj, attr_name)
    except Exception:
        return default


def _xml_type_name(com_object, value) -> str:
    type_info = None
    xml_type_method = safe_getattr(com_object, "XMLТип", None)
    if callable(xml_type_method):
        try:
            type_info = xml_type_method(value)
        except Exception:
            type_info = None
    if type_info is None:
        xml_type_value_method = safe_getattr(com_object, "XMLТипЗнч", None)
        if callable(xml_type_value_method):
            try:
                type_info = xml_type_value_method(value)
            except Exception:
                type_info = None
    type_info = call_if_callable(type_info)
    if type_info is None:
        return ""
    name = safe_getattr(type_info, "ИмяТипа", None)
    name = call_if_callable(name)
    if not name:
        name = safe_getattr(type_info, "Имя", None)
        name = call_if_callable(name)
    if not name:
        name = safe_getattr(type_info, "Name", None)
        name = call_if_callable(name)
    if name:
        try:
            name_str = str(name)
        except Exception:
            name_str = None
        if name_str:
            for old, new in (("CatalogRef.", "Справочник."), ("EnumRef.", "Перечисление.")):
                if name_str.startswith(old):
                    name_str = name_str.replace(old, new, 1)
            return name_str
    try:
        return "" if type_info is None else str(type_info)
    except Exception:
        return ""


def _stringify_query_value(com_object, value, column_name: str) -> str:
    if value is None:
        return ""
    if column_name.endswith("_Тип"):
        type_name = _xml_type_name(com_object, value)
        if type_name:
            return type_name
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        try:
            y, m, d = int(value.year), int(value.month), int(value.day)
            if hasattr(value, "hour") and hasattr(value, "minute"):
                h = int(value.hour)
                mi = int(value.minute)
                s = int(value.second) if hasattr(value, "second") else 0
                return f"{y:04d}-{m:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
            return f"{y:04d}-{m:02d}-{d:02d}"
        except (ValueError, AttributeError, TypeError):
            pass
    if hasattr(value, "_oleobj_"):
        try:
            text_value = str(value)
        except Exception:
            text_value = ""
        if text_value and "<COMObject" not in text_value:
            return text_value
        if column_name.endswith("_Тип"):
            return _xml_type_name(com_object, value)
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def get_com_connector(progids: Optional[Sequence[str]] = None):
    """
    Инициализирует COM-коннектор 1С, перебирая переданные ProgID.
    Возвращает кортеж (коннектор, использованный ProgID) или возбуждает исключение.
    """
    if win32com is None:
        raise RuntimeError(
            "Модуль pywin32 не установлен. Установите: pip install pywin32"
        )
    try:
        import pythoncom
        try:
            pythoncom.CoInitialize()
        except pythoncom.com_error as e:
            if getattr(e, "hresult", None) != -2147221008:
                raise
    except ImportError:
        pass
    except Exception:
        pass

    errors = []
    for progid in progids or DEFAULT_COM_PROGIDS:
        try:
            connector = win32com.client.Dispatch(progid)
            _log(f"Используется COM-коннектор: {progid}")
            return connector, progid
        except Exception as exc:
            errors.append((progid, exc))
    messages = "; ".join(f"{pid}: {err}" for pid, err in errors)
    raise RuntimeError(f"Не удалось создать COM-коннектор. Детали: {messages}")


def _get_short_path(path: str) -> Optional[str]:
    """
    Преобразует путь в короткий формат 8.3 (обход проблем с кириллицей в 1С COM).
    Возвращает None при ошибке.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if kernel32.GetShortPathNameW(path, buf, len(buf)):
            return buf.value
    except Exception:
        pass
    return None


def _apply_short_path_for_unicode(connection_string: str) -> str:
    """
    Заменяет путь в File="..." на короткий (8.3), если путь содержит не-ASCII.
    Обход проблем с кириллицей в путях при подключении 1С через COM.
    """
    match = re.search(r'File="([^"]*)"', connection_string)
    if not match:
        return connection_string
    path = match.group(1).rstrip("\\")
    if not path or not any(ord(c) > 127 for c in path):
        return connection_string
    short_path = _get_short_path(path)
    if short_path:
        old_part = match.group(0)
        new_part = f'File="{short_path}"'
        connection_string = connection_string.replace(old_part, new_part, 1)
        _log(f"Путь с кириллицей заменён на короткий: {short_path}")
    return connection_string


def _platform_83_exe() -> str:
    """Путь к 1cv8.exe 8.3 (для поиска comcntr.dll рядом)."""
    try:
        from com_1c.config import get_platform_83

        return get_platform_83()
    except Exception:
        return os.environ.get(
            "PLATFORM_83", r"C:\Program Files\1cv8\8.3.27.1859\bin\1cv8.exe"
        )


def _connect_v83_via_typelib(connection_string: str):
    """
    Подключение через IV8COMConnector3 + ITypeInfo (если у V83.COMConnector нет Connect в Dispatch).
    """
    import pythoncom
    import pywintypes
    import win32com.client.dynamic as win32_dynamic
    import win32com.client.gencache as gencache

    mod = None
    try:
        mod = gencache.EnsureModule(_COMCNTR_TLB_GUID, 0, 1, 0)
    except Exception:
        dll = Path(_platform_83_exe()).resolve().parent / "comcntr.dll"
        if dll.is_file():
            mod = gencache.EnsureModule(str(dll), 0, 1, 0)
    if mod is None:
        raise RuntimeError("Не удалось загрузить typelib comcntr (EnsureModule)")

    dll_path = Path(_platform_83_exe()).resolve().parent / "comcntr.dll"
    if not dll_path.is_file():
        raise RuntimeError(f"Не найден comcntr.dll: {dll_path}")

    tlib = pythoncom.LoadTypeLib(str(dll_path))
    ti = tlib.GetTypeInfoOfGuid(pywintypes.IID(_IID_IV8_COM_CONNECTOR3))
    raw = pythoncom.new(mod.COMConnector.CLSID)
    connector = win32_dynamic.Dispatch(raw, typeinfo=ti)
    return connector.Connect(connection_string)


def resolve_connection_string(db_path_or_config: str) -> Tuple[str, str]:
    """
    Определяет строку подключения к базе 1С.

    Поддерживается:
    - серверная строка (если есть ``Srvr=`` или ``Ref=``) — возвращается как есть
      (после обрезки пробелов и добавления ``;`` в конце при необходимости);
    - готовая файловая ``File="…";…``;
    - только путь к каталогу файловой базы — оборачивается в ``File="…";Usr=;Pwd=;``.
    """
    raw = (db_path_or_config or "").strip()
    if not raw:
        raise ValueError("Пустая строка подключения")

    if "Srvr=" in raw or "Ref=" in raw:
        if not raw.endswith(";"):
            raw = raw + ";"
        return raw, "Серверная база (Srvr/Ref)"

    if 'File="' in raw and ";" in raw.split("File=", 1)[-1]:
        connection_string = raw
    else:
        connection_string = f'File="{raw}";Usr=;Pwd=;'
    connection_string = _apply_short_path_for_unicode(connection_string)
    return connection_string, f"Файловая база: {raw}"


def connect_to_1c(db_path_or_config: str):
    """
    Подключается к базе данных 1С через COM.

    Args:
        db_path_or_config: путь к файловой базе, либо полная строка с ``File=…;``,
            либо серверная ``Srvr="хост";Ref="имяИБ";Usr="…";Pwd="…";`` (как в консоли кластера).

    Returns:
        COM-объект соединения или None при ошибке.
    """
    disable_proxy_env_for_1c()
    try:
        connection_string, description = resolve_connection_string(db_path_or_config)
        _log(f"Подключение: {description}")
    except Exception as exc:
        print(f"Ошибка подготовки строки подключения: {exc}")
        return None
    errors = []
    for progid in DEFAULT_COM_PROGIDS:
        try:
            connector = win32com.client.Dispatch(progid)
        except Exception as exc:
            errors.append((progid, f"Dispatch: {exc}"))
            continue
        connect_method = safe_getattr(connector, "Connect", None)
        if not callable(connect_method):
            if progid == "V83.COMConnector":
                try:
                    com_object = _connect_v83_via_typelib(connection_string)
                    _log("Подключение успешно через V83 (typelib IV8COMConnector3).")
                    return com_object
                except Exception as exc:
                    errors.append((progid, f"V83 typelib: {exc}"))
            else:
                errors.append((progid, "Connect method not available"))
            continue
        try:
            com_object = connect_method(connection_string)
            _log(f"Подключение успешно через {progid}.")
            return com_object
        except Exception as exc:
            errors.append((progid, exc))
            continue

    if errors:
        for progid, exc in errors:
            print(f"Ошибка подключения к базе ({progid}): {exc}")
    else:
        print("Ошибка: не удалось создать COM-коннектор.")
    print(
        "Возможные причины: ragent/кластер недоступен, неверная строка Srvr/Ref, "
        "несовпадение версии клиента COM и сервера (используйте V83 к серверу 8.3), "
        "база занята, нет прав или лицензии 1С."
    )
    return None


def create_query(com_object, query_text: str):
    """Создаёт объект запроса 1С с переданным текстом."""
    query = com_object.NewObject("Запрос")
    query.Текст = query_text
    return query


def get_enum_value(conn, enum_name: str, value_name: str):
    """
    Получает значение перечисления 1С для передачи в вызов процедур через COM.

    Args:
        conn: COM-объект соединения с 1С
        enum_name: имя перечисления (напр. "ИИА_ТипДиалога")
        value_name: имя значения (напр. "Агент", "Запрос1С")

    Returns:
        COM-объект значения перечисления или None при ошибке
    """
    try:
        enums = safe_getattr(conn, "Перечисления", None)
        if enums is None:
            return None
        enum_obj = safe_getattr(enums, enum_name, None)
        if enum_obj is None:
            return None
        return safe_getattr(enum_obj, value_name, None)
    except Exception:
        return None


def call_procedure(conn, module_name: str, procedure_name: str, *args):
    """
    Вызывает экспортную процедуру/функцию общего модуля 1С через COM.

    Args:
        conn: COM-объект соединения с 1С
        module_name: имя общего модуля (напр. "ИИА_ДиалогCOM")
        procedure_name: имя экспортной процедуры/функции (напр. "СоздатьДиалогИВыполнитьАгентаСинхронно")
        *args: аргументы процедуры

    Returns:
        Возвращаемое значение процедуры/функции или None при ошибке
    """
    try:
        module = safe_getattr(conn, module_name, None)
        if module is None:
            raise RuntimeError(f"Модуль '{module_name}' не найден. Проверьте ExternalConnection.")
        proc = safe_getattr(module, procedure_name, None)
        if proc is None:
            raise RuntimeError(f"Процедура '{procedure_name}' не найдена в модуле '{module_name}'.")
        if not callable(proc):
            raise RuntimeError(f"'{procedure_name}' не является вызываемым.")
        return proc(*args)
    except Exception as exc:
        raise


def structure_to_dict(com_structure):
    """
    Преобразует COM-структуру 1С в Python dict (если возможно).
    Для примитивов возвращает как есть.
    """
    if com_structure is None:
        return None
    try:
        if hasattr(com_structure, "_oleobj_"):
            # COM object — пробуем получить свойства
            result = {}
            for attr in ("СсылкаДиалога", "Успех", "Лог", "Сообщения"):
                try:
                    val = getattr(com_structure, attr, None)
                    if val is not None:
                        if hasattr(val, "_oleobj_"):
                            result[attr] = str(val)  # COM ref -> string
                        else:
                            result[attr] = val
                except Exception:
                    pass
            if result:
                return result
        return com_structure
    except Exception:
        return com_structure


def execute_query(
    com_object,
    query_text: str,
    column_names: Iterable[str],
    params: Optional[dict] = None,
) -> list:
    """
    Выполняет запрос 1С и возвращает данные в виде списка словарей.
    """
    query = create_query(com_object, query_text)
    if params:
        for name, value in params.items():
            query.УстановитьПараметр(name, value)
    result = query.Выполнить()
    selection = result.Выбрать()
    rows = []
    col_list = list(column_names)
    getter = safe_getattr(selection, "Получить", None)
    get_item = safe_getattr(selection, "__getitem__", None)

    while selection.Следующий():
        row_dict = {}
        for column_name in col_list:
            value = safe_getattr(selection, column_name, None)
            if callable(value) and not (win32com and isinstance(value, win32com.client.CDispatch)):
                value = None
            if value is None and callable(getter):
                try:
                    value = getter(column_name)
                except Exception:
                    value = None
            if value is None and callable(get_item):
                try:
                    value = get_item(column_name)
                except Exception:
                    value = None
            row_dict[column_name] = _stringify_query_value(com_object, value, column_name)
        rows.append(row_dict)
    return rows
