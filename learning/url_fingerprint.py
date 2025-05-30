import sqlite3
import os
import numpy as np
import json

class FingerprintDB:
    def __init__(self, db_path=None):
        # 统一用 config 里的 root_dir + data/urls.db
        conf_path = os.path.join(os.path.dirname(__file__), '../config/xrole.conf')
        with open(conf_path, 'r', encoding='utf-8') as f:
            conf = json.load(f)
        root_dir = str(conf.get('root_dir', ''))
        if db_path is None:
            db_path = os.path.join(root_dir, 'data/urls.db')
        else:
            if not os.path.isabs(db_path):
                db_path = os.path.join(root_dir, db_path)
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
        result = []
        for url, fp in cur.fetchall():
            # 判断 fp 是否为二进制向量还是字符串 hash
            if isinstance(fp, bytes) and len(fp) % 4 == 0:
                try:
                    arr = np.frombuffer(fp, dtype=np.float32)
                    result.append((url, arr))
                except Exception:
                    result.append((url, fp.decode('utf-8', errors='ignore')))
            else:
                try:
                    result.append((url, fp.decode('utf-8', errors='ignore')))
                except Exception:
                    result.append((url, str(fp)))
        return result

    def add_fingerprint(self, url: str, fingerprint):
        # 支持 hash(str) 或 np.ndarray
        if isinstance(fingerprint, np.ndarray):
            self.conn.execute(
                "INSERT INTO url_fingerprints (url, fingerprint) VALUES (?, ?)",
                (url, fingerprint.astype(np.float32).tobytes())
            )
        else:
            # 直接存为 utf-8 字符串
            self.conn.execute(
                "INSERT INTO url_fingerprints (url, fingerprint) VALUES (?, ?)",
                (url, str(fingerprint).encode('utf-8'))
            )
        self.conn.commit()
