# All evidence/claim/generation/delivery writes acquire this gate before row locks.
GENERATION_LOCK_KEY = int.from_bytes(b"EUmatch1", "big")
