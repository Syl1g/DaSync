# DaSync

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
   git remote add origin https://github.com/ТВОЙ_АККАУНТ/dasync.git
   git push -u origin main
   ```
2. В `docs/index.html` замени `OWNER/REPO` на `ТВОЙ_АККАУНТ/dasync`.
3. Сайт: Settings → Pages → Branch: `main`, папка `/docs`. Адрес появится там же.
4. Выпусти версию. GitHub сам соберёт установщик на Windows и приложит к релизу:
   ```
   git tag v0.1.0
   git push origin v0.1.0
   ```
   Прогресс: вкладка Actions. Готовый `DaSync-Setup.exe` появится в Releases.

Локально на Windows (нужны Python 3.12 и Inno Setup 6): `cd desktop; .\build_windows.ps1 -Version 0.1.0`

## Android (APK для скачивания)
```
cd mobile
npm install
npx eas-cli login
npx eas-cli build --platform android --profile preview
```
Скачай готовый APK по ссылке из терминала, назови `DaSync.apk` и приложи к релизу на GitHub.
Перед магазинами замени `com.example.dasync` в `mobile/app.json` на свой идентификатор.

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
