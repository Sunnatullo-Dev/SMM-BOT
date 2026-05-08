# Server Deploy

Hozirgi production tavsiya qilingan variant:

- `main.py` bitta `web` service ichida ishlaydi
- shu process ichida `FastAPI` ham, `Telegram polling` ham yuradi
- SQLite bitta process ichida qoladi, shuning uchun `web` va `worker` orasida baza bo'linib ketmaydi

## 1. Muhim env qiymatlar

Majburiy:

- `BOT_TOKEN`
- `ADMINS`
- `SMM_API_KEY`
- `SMM_API_URL=https://locksmm.com/api/v2`
- `SMS_API_KEY`
- `SMS_API_URL=https://locksmm.uz`
- `CARD_NUMBER`
- `CARD_HOLDER`
- `USD_RATE=12850`
- `DEFAULT_SMM_MARKUP_PERCENT=30`
- `REFERRAL_BONUS=500`
- `DAILY_BONUS_DEFAULT=500`

Mini App ishlatsa:

- `WEB_APP_ALLOWED_ORIGINS=https://sizning-domeningiz`

## 2. Render

Render uchun [render.yaml](C:/Users/Ucer/Desktop/SMMBOT/render.yaml) ichida bitta service tayyor:

- type: `web`
- start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- healthcheck: `/healthz`

Deploydan keyin:

1. Render dashboardda env variablelarni kiriting
2. `Manual Deploy` yoki `Redeploy` qiling
3. `/healthz` `200` qaytarayotganini tekshiring

## 3. Railway

Railway'da ham bitta service yetadi:

- Start Command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

- Healthcheck Path:

```text
/healthz
```

`Root Directory` bo'sh qolishi kerak.

## 4. Lokal smoke test

```bash
python -m compileall .
python deploy_check.py
```

## 5. Nega bitta service

Avvalgi sxemada:

- `bot.py` alohida worker
- `web_app_api.py` alohida web

edi. Bu SQLite bilan xavfli, chunki:

- env va baza state ikkala service'da ajralib ketadi
- hosting platforma har service uchun alohida disk/instance berishi mumkin
- admin paneldagi o'zgarishlar yoki `database.db` boshqa service'da ko'rinmay qolishi mumkin

Shu sabab SQLite bilan eng xavfsiz variant hozircha `single service`.

## 6. Muhim eslatmalar

- `MemoryStorage` ishlatilmoqda, shu sabab 1 ta instance bilan ishlating
- `uvicorn --workers` ko'paytirmang
- SQLite production uchun vaqtinchalik yechim; katta yuklama uchun keyin Postgresga o'tish kerak
- `.env` va `database.db` gitga kirmaydi, serverda env qiymatlarini qo'lda kiritish kerak
