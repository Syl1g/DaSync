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

