import bcrypt

from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.crypto import constant_time_compare


class LaravelBCryptPasswordHasher(BasePasswordHasher):
    """Verify imported Laravel $2y$ bcrypt hashes and upgrade them on login."""

    algorithm = "laravel_bcrypt"

    def salt(self):
        return ""

    def encode(self, password, salt):
        encoded = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        return f"{self.algorithm}${encoded}"

    def verify(self, password, encoded):
        prefix = f"{self.algorithm}$"
        if not encoded.startswith(prefix):
            return False
        raw = encoded[len(prefix):].replace("$2y$", "$2b$", 1)
        try:
            return bcrypt.checkpw(password.encode(), raw.encode())
        except ValueError:
            return False

    def safe_summary(self, encoded):
        return {"algorithm": self.algorithm, "hash": mask_hash(encoded, show=15)}

    def must_update(self, encoded):
        return True

    def harden_runtime(self, password, encoded):
        constant_time_compare(encoded, encoded)
