# DaSync для разработчиков

Это инструкция по сборке и выпуску. Описание для пользователей лежит в [README](../README.md).

Управляй ноутбуком с телефона по домашней Wi-Fi. Без аккаунтов и облака.

```
desktop/   приложение для Windows (Python) + установщик (PyInstaller, Inno Setup)
mobile/    приложение для iPhone и Android (Expo, React Native, TypeScript)
docs/      лендинг со ссылками на скачивание (GitHub Pages)
.github/   облачная сборка установщика
```

## Выпуск версии за 10 минут

1. Создай на GitHub **публичный** репозиторий (из приватного скачивать без входа нельзя) и загрузи туда проект:
   ```
   git init && git add . && git commit -m "DaSync"
   git branch -M main
   git remote add origin https://github.com/Syl1g/DaSync.git
   git push -u origin main
   ```
2. В `docs/index.html` замени `OWNER/REPO` на `Syl1g/DaSync`.
3. Сайт: Settings → Pages → Branch: `main`, папка `/docs`. Адрес появится там же.
4. Выпусти версию. GitHub сам соберёт установщик на Windows и приложит к релизу:
   ```
   git tag v0.1.0
   git push origin v0.1.0
   ```
   Прогресс: вкладка Actions. Готовый `DaSync-Setup.exe` появится в Releases.

Локально на Windows (нужны Python 3.12 и Inno Setup 6): `cd desktop; .\build_windows.ps1 -Version 0.1.0`

## Android (APK)
APK собирается на GitHub вместе с установщиком Windows: при выпуске версии (`v1.0.1`) прикладываются и `DaSync-Setup.exe`, и `DaSync.apk`.
Всегда сначала нажимай «Publish release» на сайте GitHub, а потом жди сборки: так оба файла попадают в один релиз.
Вручную: Actions → «Android APK» → Run workflow, файл появится в блоке Artifacts.
Идентификатор приложения: `io.github.syl1g.dasync` (менять нужно до первой публикации в Google Play, потом нельзя).
APK подписан отладочным ключом: для установки напрямую этого достаточно, для Google Play потребуется свой ключ.

## iPhone
- Сейчас: веб-версия в Safari (наведи камеру на QR из окна DaSync, «На экран Домой»).
- Дальше: TestFlight с публичной ссылкой (до 10 000 тестеров, сборка живёт 90 дней, первую сборку проверяет Apple), затем App Store. Нужен платный Apple Developer. Собирать можно без Mac: `eas build -p ios`.

## Подпись приложения для Windows
Без подписи Windows показывает SmartScreen («Система Windows защитила ваш компьютер»). Варианты:
- Microsoft Store (MSIX): без предупреждений, бесплатная переупаковка.
- Azure Artifact Signing: около 10 $/месяц, для физлиц только США и Канада, организации в США, Канаде, ЕС и Великобритании.
- OV-сертификат у центра сертификации: ориентировочно 150-500 $/год.
Даже с подписью репутация SmartScreen копится неделями. В `desktop.yml` оставлено место для шага подписи.

## Если телефон не видит ноутбук
Windows должна считать Wi-Fi «Частной» сетью: правило брандмауэра, которое ставит установщик, действует только для частных сетей.

## Google Play
Всё нужное для публикации лежит в `store/`: тексты, анкеты, графика и пошаговый чек-лист `store/PUBLISH_CHECKLIST.md`.
Главное: ключ загрузки делается скриптом `tools/make_upload_key.py`, потом три секрета в GitHub, после чего сборка Android сама выдаёт `DaSync.aab` для Google Play.
Демо-режим в приложении («Посмотреть в демо-режиме» на первом экране) нужен проверяющим: без ноутбука они иначе не смогут ничего проверить.

## Как сделать проект находимым в поиске
1. Репозиторий: на главной странице нажми шестерёнку рядом с About, впиши описание, адрес сайта `https://syl1g.github.io/DaSync/` и темы (topics): `remote-control`, `remote-desktop`, `phone-as-touchpad`, `laptop-remote`, `windows`, `android`, `ios`, `react-native`, `expo`, `dasync`.
2. Сайт: Settings → Pages → Branch `main`, папка `/docs`.
3. Google Search Console (search.google.com/search-console): добавь ресурс «Префикс URL» `https://syl1g.github.io/DaSync/`, подтверди владение (проще всего HTML-файл: скачай его и загрузи в `docs/`), затем «Проверка URL» → «Запросить индексирование», в разделе Sitemaps добавь `sitemap.xml`.
4. Ссылки на проект с других мест (это главный фактор): пост в Telegram и Reddit, Habr, AlternativeTo, Product Hunt. Чем больше надёжных сайтов ссылается на репозиторий и сайт, тем быстрее и выше Google их покажет.
