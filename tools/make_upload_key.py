#!/usr/bin/env python3
"""
Создаёт ключ загрузки для Google Play (один раз!) и готовит значения для секретов GitHub.

    pip install cryptography
    python make_upload_key.py

ВАЖНО: файл dasync-upload.p12 и пароль нужно сохранить минимум в двух надёжных местах
(менеджер паролей, облако с шифрованием). Потеряешь, и придётся восстанавливать ключ через поддержку Google.
Никогда не загружай эти файлы в репозиторий.
"""
import base64
import secrets
import sys
from datetime import datetime, timedelta, timezone

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
except ImportError:
    sys.exit("Сначала выполни: pip install cryptography")

ALIAS = "dasync-upload"
password = secrets.token_urlsafe(18)

key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
name = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "DaSync Upload"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DaSync"),
])
now = datetime.now(timezone.utc)
cert = (
    x509.CertificateBuilder()
    .subject_name(name).issuer_name(name)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - timedelta(days=1))
    .not_valid_after(now + timedelta(days=10000))  # около 27 лет, Google требует не меньше 25
    .sign(key, hashes.SHA256())
)

# Совместимый с Java 11/17/21 формат PKCS12
enc = (
    serialization.PrivateFormat.PKCS12.encryption_builder()
    .kdf_rounds(50000)
    .key_cert_algorithm(pkcs12.PBES.PBESv2SHA256AndAES256CBC)
    .hmac_hash(hashes.SHA256())
    .build(password.encode())
)
data = pkcs12.serialize_key_and_certificates(ALIAS.encode(), key, cert, None, enc)

open("dasync-upload.p12", "wb").write(data)
b64 = base64.b64encode(data).decode()
open("dasync-upload.p12.base64.txt", "w").write(b64)
open("dasync-upload-secrets.txt", "w", encoding="utf-8").write(
    f"UPLOAD_KEYSTORE_BASE64  = (содержимое файла dasync-upload.p12.base64.txt)\n"
    f"UPLOAD_STORE_PASSWORD   = {password}\n"
    f"UPLOAD_KEY_ALIAS        = {ALIAS}\n"
)
print("Готово. Создано 3 файла:")
print("  dasync-upload.p12              сам ключ (СОХРАНИ, не теряй)")
print("  dasync-upload.p12.base64.txt   его текстовая копия для GitHub")
print("  dasync-upload-secrets.txt      пароль и имя ключа")
print("\nТеперь на GitHub: Settings → Secrets and variables → Actions → New repository secret.")
print("Добавь три секрета: UPLOAD_KEYSTORE_BASE64, UPLOAD_STORE_PASSWORD, UPLOAD_KEY_ALIAS.")
print("Потом сохрани .p12 и пароль в двух местах и удали txt-файлы с компьютера.")
