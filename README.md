# check-in.html

Лендинг «Дом у Волги в Лаишевском районе» с рабочим сбором лидов, антиспам-защитой, retry webhook и уведомлениями.

## Что реализовано

- Рабочая форма заявки (A/B варианты: `имя+телефон` и `только телефон`).
- Отправка лидов `POST /api/lead`.
- Логирование лидов в `data/leads.jsonl`.
- Проброс в webhook через `LEAD_WEBHOOK_URL`.
- Защита от спама: honeypot (`website`) + серверная проверка.
- Защита API: CORS whitelist, rate limit, IP throttling.
- Анти-бот: reCAPTCHA v3 (если заполнены ключи окружения).
- Надежность: retry webhook (3 попытки) + уведомления в Telegram/email-webhook.
- Подключены GTM, GA4, Google Ads tag, Meta Pixel (placeholder ID).
- События: `cta_click`, `form_submit`, `scroll_50`, `scroll_90`.
- A/B форма 50/50 с фиксацией варианта в `localStorage`.
- OG-баннер `og-cover.svg` (строго 1200×630, текстовый формат без бинарных файлов).

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Открыть: `http://localhost:8080`

## Docker запуск

```bash
docker compose up -d --build
```

Открыть: `http://localhost:8080`

Health-check:

```bash
curl -f http://localhost:8080/health
```

## Переменные окружения

- `LEAD_WEBHOOK_URL` — URL вашего Make/Zapier/CRM webhook.
- `LEAD_LOG_DIR` — директория для логов лидов (по умолчанию `data`).
- `ALLOWED_ORIGINS` — список origin через запятую для CORS, например `https://your-domain.com,https://www.your-domain.com`.
- `MAX_REQUESTS_PER_MINUTE_IP` — лимит запросов с IP в минуту (по умолчанию `20`).
- `MAX_LEADS_PER_HOUR_IP` — лимит лидов с IP в час (по умолчанию `10`).
- `RECAPTCHA_SECRET` — секретный ключ reCAPTCHA v3 (на фронте замените `RECAPTCHA_SITE_KEY`).
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — параметры Telegram-оповещений.
- `ALERT_EMAIL_WEBHOOK_URL` — webhook для e-mail уведомлений о новом лиде.

Пример:

```bash
export LEAD_WEBHOOK_URL="https://hook.eu1.make.com/xxxx"
export ALLOWED_ORIGINS="https://waterline-house.example,https://www.waterline-house.example"
```

## Что заменить перед продом

- `GTM-XXXXXXX`, `G-XXXXXXXXXX`, `AW-XXXXXXXXX`, `Meta Pixel ID` в `index.html`.
- `RECAPTCHA_SITE_KEY` в `index.html`.
- Домен `https://waterline-house.example/` в `index.html`, `robots.txt`, `sitemap.xml`.
- Контакты и ссылки соцсетей в JSON-LD (`sameAs`, `email`, `telephone`).
- Юридические данные: ИНН/ОГРН и название застройщика.
- Плейсхолдеры фото/видео заменить на реальные материалы объекта.

## Обязательная валидация перед запуском трафика

1. Проверить `og-cover.svg` (строго `1200x630`) и превью в Telegram/WhatsApp/Facebook Debugger.
2. Проверить в real-time события `cta_click`, `form_submit`, `scroll_50`, `scroll_90` в GTM/GA4.
3. Проверить прием событий в Meta Pixel и Google Ads.
4. Сверить оффер (цена от 9,5 млн ₽) с фактическими объектами и наполнением.
5. Проверить mobile PageSpeed и целевое значение `>=80`.

## Smoke-тест перед запуском

Локальный интеграционный прогон (API, retry webhook, CORS, reCAPTCHA-ветка, уведомления, rate limit):

```bash
python scripts/smoke_test.py
```

Проверка OG-баннера:

```bash
python scripts/check_og_dimensions.py
```

## API лидов

`POST /api/lead` (JSON)

Пример payload:

```json
{
  "name": "Иван",
  "phone": "+79990000000",
  "utm_source": "google",
  "utm_medium": "cpc",
  "utm_campaign": "volga",
  "website": ""
}
```

Успех:

```json
{ "ok": true, "forwarded": true }
```
