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


class MissingSecret(RuntimeError):
    """Raised when decryption is attempted without the key that produced the ciphertext."""


def load_or_create_secret(path: Path = SECRET_PATH, create: bool = True) -> bytes:
    """Load the Fernet secret. `create=False` refuses to invent one.

    Creating a secret on the DECRYPT path was a real bug, found by cloning this repo fresh and
    running the documented Phase 4 command. `answer_key.enc` is committed but the secret never
    is, so a fresh clone would silently generate a brand-new random key, fail with a bare
    `InvalidToken`, and leave a bogus `.answer_key_secret` behind that guaranteed the same opaque
    failure on every retry. Decryption now refuses up front and explains itself.
    """
    if path.exists():
        return path.read_bytes().strip()
    if not create:
        raise MissingSecret(
            f"No Fernet secret at {path}.\n"
            f"`answer_key.enc` is committed but the key that decrypts it is deliberately NOT — "
            f"the planted-error answers are meant to stay hidden until the walkthrough.\n"
            f"This is expected behaviour in a fresh clone, not a broken repo.\n"
            f"To run the verification layer against your own key, create a new plaintext "
            f"`answer_key.json` and run:\n"
            f"    python -m src.verify.keystore encrypt answer_key.json answer_key.enc\n"
            f"which will generate a secret for you. See README section 6 (Verification layer)."
        )
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
    # create=False: never invent a key on the decrypt path (see load_or_create_secret).
    secret = secret or load_or_create_secret(create=False)
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
