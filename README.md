# umpk-schedule

Исходники статического сайта. GitHub Pages публикует папку `docs/`,
домен указан в `docs/CNAME`.

Данные собирает `tools/build_data.py` — его же по расписанию запускает
`.github/workflows/update.yml`.

## Локальный запуск

```bash
python -m pip install -r requirements.txt
python tools/build_data.py
python -m http.server 8000 --directory docs
```

`python tools/check.py` — диагностика разбора исходных таблиц.
