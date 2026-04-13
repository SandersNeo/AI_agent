# Пакет Vanessa Automation для UI-тестов формы ИИ агента

В эту папку собраны артефакты для запуска UI-тестов Vanessa Automation:

- `vanessa-automation-single.epf` – обработка Vanessa Automation (single поставка).
- `TestAIAgent.feature`, `OpenChatForm.feature`, `AttachFiles.feature` – feature-файлы для smoke/regression UI-проверок.
- `update_and_run_vanessa.py` – Python-скрипт, который обновляет конфигурацию БД и запускает Vanessa с нужным сценарием.
- `VAParams.json` – пример настроек запуска (создаётся автоматически, если удалить).
- `logs\` – каталог, куда будут складываться `update-db.log` и `vanessa.log`.

## Как перенести и запустить

1. Скопируйте папку `vanessa` в новый проект.
2. Проверьте/исправьте в `.env` параметры `1C_CONNECTION_STRING`, `PLATFORM_85`, а при необходимости передайте `--user-name` и `--password`.
3. Запустите Python-скрипт:

   ```bash
   python automation/vanessa/update_and_run_vanessa.py --feature-file automation/vanessa/TestAIAgent.feature
   python automation/vanessa/update_and_run_vanessa.py --feature-file automation/vanessa/AttachFiles.feature
   ```

После успешного выполнения в папке `logs` появятся файлы с результатами обновления базы и прогонки сценария.


