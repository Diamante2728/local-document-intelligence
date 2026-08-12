"""Encrypt / decrypt the planted-error answer key (Fernet).

`answer_key.json` (plaintext) is NEVER committed — see .gitignore. Only `answer_key.enc` is
tracked. The key material lives in `.answer_key_secret` (also gitignored) so the encrypted
blob in git is useless on its own; the secret is revealed at the walkthrough.

Usage:
    python -m src.verify.keystore encrypt answer_key.json answer_key.enc
    python -m src.verify.keystore decrypt answer_key.enc
"""
import json
import sys
from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET_PATH = REPO_ROOT / ".answer_key_secret"


def load_or_create_secret(path: Path = SECRET_PATH) -> bytes:
    if path.exists():
        return path.read_bytes().strip()
    secret = Fernet.generate_key()
    path.write_bytes(secret)
    path.chmod(0o600)
    return secret


def encrypt_file(plain_path: Path, enc_path: Path, secret: bytes = None) -> None:
    secret = secret or load_or_create_secret()
    data = Path(plain_path).read_bytes()
    json.loads(data)  # fail loudly on malformed JSON rather than encrypting garbage
    Path(enc_path).write_bytes(Fernet(secret).encrypt(data))


def decrypt_file(enc_path: Path, secret: bytes = None):
    secret = secret or load_or_create_secret()
    return json.loads(Fernet(secret).decrypt(Path(enc_path).read_bytes()))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    action = sys.argv[1]
    if action == "encrypt":
        encrypt_file(Path(sys.argv[2]), Path(sys.argv[3]))
        print(f"encrypted {sys.argv[2]} -> {sys.argv[3]}")
    elif action == "decrypt":
        json.dump(decrypt_file(Path(sys.argv[2])), sys.stdout, indent=2)
        print()
    else:
        print(f"unknown action {action!r}")
        sys.exit(1)


if __name__ == "__main__":
    main()
