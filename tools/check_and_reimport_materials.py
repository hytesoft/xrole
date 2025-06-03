import os
import sqlite3
import requests
import json
from glob import glob

# 配置
MATERIAL_DIR = './data/role_materials'
FINGERPRINT_DB = 'data/urls.db'
QDRANT_URL = 'http://192.168.3.27:9001'
QDRANT_COLLECTION = 'xrole_docs'

# 支持的文件类型
ALLOWED_EXTS = ['.pdf', '.doc', '.docx']

def get_all_files():
    files = []
    for ext in ALLOWED_EXTS:
        files.extend(glob(os.path.join(MATERIAL_DIR, f'**/*{ext}'), recursive=True))
    return files

def get_fingerprinted_files():
    conn = sqlite3.connect(FINGERPRINT_DB)
    cur = conn.cursor()
    cur.execute("SELECT url FROM url_fingerprints")
    rows = cur.fetchall()
    conn.close()
    # 只保留本地文件
    return set([r[0].replace('file://', '').replace('./', '').lstrip('/') for r in rows])

def get_qdrant_count():
    url = f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/count"
    resp = requests.post(url, json={})
    if resp.ok:
        return resp.json().get('result', {}).get('count', 0)
    return 0

def main():
    all_files = get_all_files()
    all_files_rel = [os.path.relpath(f, '.') for f in all_files]
    fingerprinted = get_fingerprinted_files()
    print(f"本地共发现 {len(all_files)} 个支持的文件。")
    print(f"指纹库已记录 {len(fingerprinted)} 个文件。Qdrant 当前向量数: {get_qdrant_count()}\n")

    not_in_fingerprint = [f for f in all_files_rel if f.lstrip('./') not in fingerprinted]
    in_fingerprint = [f for f in all_files_rel if f.lstrip('./') in fingerprinted]

    print("未入指纹库的文件:")
    for f in not_in_fingerprint:
        print(f"  {f}")
    print("\n已入指纹库的文件:")
    for f in in_fingerprint:
        print(f"  {f}")
    print("\n如需自动补导未入库文件，请手动将这些文件移到空目录后再运行 fetch_and_learn.py。\n")

if __name__ == "__main__":
    main()
