import sqlite3
import os
import numpy as np

class FingerprintDB:
    def __init__(self, db_path="data/urls.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS url_fingerprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                fingerprint BLOB
            )
            """
        )
        self.conn.commit()

    def get_all_fingerprints(self):
        cur = self.conn.execute("SELECT url, fingerprint FROM url_fingerprints")
        return [(url, np.frombuffer(fp, dtype=np.float32)) for url, fp in cur.fetchall()]

    def add_fingerprint(self, url: str, fingerprint: np.ndarray):
        self.conn.execute(
            "INSERT INTO url_fingerprints (url, fingerprint) VALUES (?, ?)",
            (url, fingerprint.astype(np.float32).tobytes())
        )
        self.conn.commit()
