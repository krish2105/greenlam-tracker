"""Generate a VAPID key pair.

    python -m app.vapid

Run once per deployment. The private key is a secret and belongs in the
environment, never in the repository; the public key is handed to every browser
that subscribes, so it is not sensitive at all.

Rotating the pair invalidates every existing subscription — browsers encrypt to
the public key they were given — so every phone would have to re-subscribe. Do
it only if the private key leaks.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(raw: bytes) -> str:
    """URL-safe base64 with the padding stripped, which is what VAPID wants."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = _b64(
        key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
    )
    return public, private


if __name__ == "__main__":
    public, private = generate()
    print("VAPID_PUBLIC_KEY=" + public)
    print("VAPID_PRIVATE_KEY=" + private)
    print()
    print("Set both in the API's environment. The private key is a secret.")
