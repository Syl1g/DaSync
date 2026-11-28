# Сторонние компоненты

DaSync использует открытые библиотеки. Их лицензии совместимы с GNU GPL v3, под которой распространяется сам DaSync (см. `LICENSE`).
Исходный код DaSync публичный, поэтому требования копилефт-лицензий (GPL, LGPL) выполняются: ты можешь получить исходники и собрать программу сам по инструкции из `docs/DEVELOPING.md`.

## Программа для Windows (desktop/)

| Компонент | Лицензия |
|---|---|
| PyAutoGUI, PyGetWindow, PyRect | BSD |
| PyMsgBox, MouseInfo | GPL-3.0 или новее |
| PyScreeze, PyTweening, six | MIT |
| pyperclip, qrcode | BSD |
| psutil | BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| pystray | LGPL-3.0 |
| PyInstaller (сборка) | GPL-2.0 с исключением для загрузчика: собранные программы можно распространять под любой лицензией |
| Inno Setup (сборка установщика) | Inno Setup License |

## Мобильное приложение (mobile/)

Основные зависимости: Expo, React, React Native, `react-native-svg`, `@noble/hashes` и модули Expo (камера, хранилище ключей, файлы, галерея и др.). Все под лицензией MIT.
Всего в сборку входит около 450 пакетов, в основном под MIT, ISC, BSD, Apache-2.0 и MPL-2.0.
Полный список можно получить командой `npx license-checker --production` в папке `mobile`.
Файл `mobile/LICENSE` относится к заготовке проекта от Expo (лицензия 0BSD).

## Название и логотип

Название «DaSync» и логотип в лицензию GPL не входят. Если делаешь свою версию, выбери другое имя и значок.
