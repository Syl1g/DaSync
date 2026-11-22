# DaSync

Управляй ноутбуком с телефона по домашней Wi-Fi. Без аккаунтов и облака.

```
desktop/   приложение для Windows (Python) + установщик (PyInstaller, Inno Setup)
mobile/    приложение для iPhone и Android (Expo, React Native, TypeScript)
docs/      лендинг со ссылками на скачивание (GitHub Pages)
.github/   облачная сборка установщика
```


## Android (APK для скачивания)
```
cd mobile
npm install
npx eas-cli login
npx eas-cli build --platform android --profile preview
```


## iPhone
- Сейчас: веб-версия в Safari (наведи камеру на QR из окна DaSync, «На экран Домой»).
- Дальше: TestFlight с публичной ссылкой `eas build -p ios`.

## Подпись приложения для Windows
Без подписи Windows показывает SmartScreen («Система Windows защитила ваш компьютер»). Варианты:
- Microsoft Store (MSIX): без предупреждений, бесплатная переупаковка.
- Azure Artifact Signing: около 10 $/месяц, для физлиц только США и Канада, организации в США, Канаде, ЕС и Великобритании.
- OV-сертификат у центра сертификации: ориентировочно 150-500 $/год.
Даже с подписью репутация SmartScreen копится неделями. В `desktop.yml` оставлено место для шага подписи.

## Если телефон не видит ноутбук
Windows должна считать Wi-Fi «Частной» сетью: правило брандмауэра, которое ставит установщик, действует только для частных сетей.
