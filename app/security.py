from cryptography.fernet import Fernet
import os

class SecurityManager:
    def __init__(self, key_path: str = "secret.key"):
        self.key_path = key_path
        self.cipher = self._load_or_create_key()

    def _load_or_create_key(self):
        if os.path.exists(self.key_path):
            with open(self.key_path, "rb") as key_file:
                key = key_file.read()
        else:
            key = Fernet.generate_key()
            with open(self.key_path, "wb") as key_file:
                key_file.write(key)
        return Fernet(key)

    def encrypt_secret(self, plain_text: str) -> str:
        return self.cipher.encrypt(plain_text.encode()).decode()

    def decrypt_secret(self, encrypted_text: str) -> str:
        return self.cipher.decrypt(encrypted_text.encode()).decode()
