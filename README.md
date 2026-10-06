# HH.ru Employer Research Parser

Система для исследования работодателей на HH.ru с фокусом на АХО-вакансии и обогащение контактной информацией.

## Возможности

- **Поиск вакансий** по ключевым словам АХО (административно-хозяйственная часть)
- **Извлечение работодателей** из результатов поиска
- **Обогащение контактов** — официальные сайты, телефоны, email, адреса
- **Entity resolution** — разрешение конфликтов между источниками
- **XLSX экспорт** — выгрузка в Excel с несколькими листами
- **Streamlit дашборд** — интерактивный интерфейс для анализа
- **Аналитика** — покрытие контактов, распределение по регионам, свежесть вакансий

## Установка

### Требования

- Python 3.10+
- pip

### Установка зависимостей

```bash
cd D:\Hh.ru
pip install -e ".[dev]"
```

Для дашборда:
```bash
pip install -e ".[dashboard]"
```

## Использование

### 1. Инициализация базы данных

```bash
hh-parser init-db
```

### 2. Поиск вакансий

```bash
# Поиск по всем ключевым словам
hh-parser search

# Поиск с ограничением по страницам
hh-parser search --max-pages 5

# Поиск по конкретному региону (area ID)
hh-parser search --area 1

# Поиск по кастомным ключевым словам
hh-parser search --keywords "начальник АХО" --keywords "facility manager"
```

### 3. Загрузка деталей работодателей

```bash
# Загрузить все работодатели
hh-parser fetch-employers --all

# Загрузить конкретного работодателя
hh-parser fetch-employers --employer-id 12345
```

### 4. Обогащение контактов

```bash
# Обогастить всех работодателей
hh-parser enrich --limit 100

# Обогастить конкретного работодателя
hh-parser enrich-one 12345
```

### 5. Экспорт в XLSX

```bash
# Экспорт с автоматическим именем файла
hh-parser export

# Экспорт в конкретный файл
hh-parser export --output reports/my_export.xlsx

# Экспорт с фильтром по signal score
hh-parser export --min-score 0.5
```

### 6. Дашборд

```bash
streamlit run hh_parser/dashboard/app.py
```

Откроется в браузере на `http://localhost:8501`

### 7. Статистика

```bash
hh-parser stats
```

### 8. Справочные команды

```bash
# Список регионов (areas)
hh-parser areas

# Список ключевых слов
hh-parser keywords
```

## Структура проекта

```
D:\Hh.ru\
├── hh_parser/              # Основной пакет
│   ├── api/                # HH.ru API клиент
│   ├── search/             # Поиск вакансий и извлечение работодателей
│   ├── db/                 # База данных (SQLite)
│   ├── enrichment/         # Обогащение контактов
│   ├── export/             # XLSX экспорт
│   ├── dashboard/          # Streamlit дашборд
│   └── cli.py              # CLI интерфейс
├── tests/                  # Тесты
├── data/                   # Данные (gitignore)
│   ├── hh_parser.db        # SQLite база
│   └── cache/              # HTTP кэш
├── reports/                # Экспорты (gitignore)
├── config.yaml             # Конфигурация
└── pyproject.toml          # Зависимости
```

## База данных

SQLite с WAL-режимом. Основные таблицы:

- `employers` — работодатели
- `vacancies` — вакансии
- `employer_vacancies` — связь работодателей и вакансий
- `contacts` — обогащённые контакты с provenance
- `enrichment_log` — лог обогащения
- `search_runs` — история поисковых запросов

## Ключевые слова

Поиск ведётся по следующим категориям:

### AHO Management (Руководство АХО)
- начальник АХО
- руководитель АХО
- заместитель директора по АХР
- административный директор
- и др.

### Facility Operations (Эксплуатация)
- facility manager
- менеджер по эксплуатации
- начальник отдела эксплуатации
- и др.

### Administrative Support (Административная поддержка)
- АХО
- административно-хозяйственная
- заведующий хозяйством
- и др.

### Maintenance (Техническое обслуживание)
- главный инженер по эксплуатации
- технический директор по эксплуатации

## Rate Limiting

- 25 запросов/минуту (анонимный доступ)
- 1800 запросов/день
- Автоматические retry при 429/5xx

## Конфигурация

`config.yaml`:

```yaml
search:
  per_page: 100
  max_pages: 20
  search_field: "name"

enrichment:
  enabled: true
  ttl_hours: 168  # 7 дней
  batch_size: 50
  request_timeout: 15.0

rate_limit:
  requests_per_minute: 25
  requests_per_day: 1800
```

## Тесты

```bash
pytest
```

## Лицензия

Research use only.

## Ограничения

- Анонимный доступ к HH.ru API (без токена)
- Ограничения по частоте запросов
- Не все работодатели имеют публичные контакты
- Обогащение работает только с публично доступной информацией
