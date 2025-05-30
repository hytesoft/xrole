import os
# 彻底清理所有代理和 SSL 相关环境变量
for k in [
    "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
    "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy",
    "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR"
]:
    os.environ.pop(k, None)

import importlib.metadata
print("[版本] qdrant-client:", importlib.metadata.version("qdrant-client"))
print("[版本] httpx:", importlib.metadata.version("httpx"))

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from starlette.types import Lifespan
import os
import json
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
import requests
import hashlib
import numpy as np
from learning.url_fingerprint import FingerprintDB
import shutil
from learning.fetch_and_learn import fetch_and_learn, import_materials
from fastapi.staticfiles import StaticFiles
from qdrant_client.http.models import Distance, VectorParams
from typing import Dict, Any
from pydantic import BaseModel
from fastapi.openapi.docs import get_swagger_ui_html

# 允许的扩展名和 MIME 类型（全局定义，供 API 路由使用）
ALLOWED_EXTS = [
    ".txt", ".md", ".pdf", ".ppt", ".pptx", ".mp3", ".wav", ".mp4", ".avi", ".mov", ".doc", ".docx"
]
ALLOWED_MIME = [
    "text/plain", "application/pdf", "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "audio/mpeg", "audio/wav", "video/mp4", "video/x-msvideo", "video/quicktime", "video/x-m4v",
    "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
]

# 读取配置文件
def load_config(path: str = "config/xrole.conf") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# 初始化 Qdrant 客户端
qdrant_conf = config.get("qdrant", {})
print("[Qdrant] connect url:", qdrant_conf.get("url"))
qdrant_client = QdrantClient(
    url=(qdrant_conf.get("url") or "https://vdb.colas.icu:443").replace("https://vdb.colas.icu", "https://vdb.colas.icu:443"),  # 强制加端口 443
    api_key=qdrant_conf.get("api_key"),
    prefer_grpc=False,
    verify=False
    # https=True,  # 不要加这个参数
)
# 自动创建 collection（如不存在）
def ensure_qdrant_collection(collection_name, vector_size=384):
    print("[Qdrant] 确保 collection 存在:", collection_name)
    if not qdrant_client.collection_exists(collection_name):
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
        )

# 初始化向量模型（支持多模型配置，自动本地加载）
embedding_models = config.get("embedding_models")
if not embedding_models:
    embedding_models = [{"name": "paraphrase-multilingual-MiniLM-L12-v2"}]
embedder_dict = {}
# 强制 root_dir 为 xrole 目录
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))
for m in embedding_models:
    model_name = m["name"]
    # 如果不是绝对路径，拼成 xrole/models/sentence-transformers/model_name
    if not os.path.isabs(model_name):
        local_model_path = os.path.join(root_dir, "models", "sentence-transformers", model_name)
        local_model_path = os.path.abspath(local_model_path)
    else:
        local_model_path = model_name
    try:
        print(f"[embedding] 加载: {local_model_path}")
        embedder_dict[model_name] = SentenceTransformer(local_model_path)  # 去掉 local_files_only 参数
    except Exception as e:
        print(f"[embedding] 加载失败: {model_name} -> {e}")
# 默认用第一个模型
embedder = embedder_dict[embedding_models[0]["name"]]

# 用 async def lifespan 事件，FastAPI 实例化时传 lifespan 参数
async def lifespan(app: FastAPI):
    fetch_and_learn_with_log()
    scheduler.add_job(fetch_and_learn_with_log, 'interval', hours=span_hours, next_run_time=None)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="xrole 智能助手 API", lifespan=lifespan)



class QueryRequest(BaseModel):
    text: str
    top_k: int = 3

@app.post("/query")
async def query_api(req: QueryRequest):
    # 1. 文本转向量
    vector = embedder.encode(req.text).tolist()
    # 2. Qdrant 检索相似内容
    search_result = qdrant_client.search(
        collection_name="xrole_docs",  # 假设你的 collection 叫这个
        query_vector=vector,
        limit=req.top_k
    )
    docs = [hit.payload.get("content", "") for hit in search_result]
    # 3. 构造 prompt，调用大模型
    llm_conf = config.get("llm", {})
    prompt = f"{config.get('prompt', '')}\n用户输入：{req.text}\n相关知识：{docs}\n请给出专业解答："
    llm_resp = requests.post(
        llm_conf.get("base_url"),
        headers={"Authorization": f"Bearer {llm_conf.get('api_key', '')}"},
        json={
            "model": llm_conf.get("model"),
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=30
    )
    answer = llm_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "无结果")
    return {
        "input": req.text,
        "related_docs": docs,
        "answer": answer
    }

# 新增：sqlite本地指纹库管理
fingerprint_db = FingerprintDB()

def cosine_sim(a, b):
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

@app.post("/add_url")
async def add_url_api(data: Dict[str, str]):
    url = data.get("url")
    content = data.get("content")
    if not url or not content:
        return {"error": "url 和 content 必填"}
    # 1. 内容向量化
    vector = embedder.encode(content)
    # 2. 与本地所有指纹比对
    exists = False
    for _, fp in fingerprint_db.get_all_fingerprints():
        sim = cosine_sim(vector, fp)
        if sim > 0.95:
            exists = True
            break
    if exists:
        return {"msg": "内容已存在（相似度大于0.95）", "exists": True}
    # 3. 新内容，写入本地指纹库和Qdrant
    fingerprint_db.add_fingerprint(url, vector)
    # 入Qdrant
    qdrant_client.upsert(
        collection_name="xrole_docs",
        points=[{
            "id": hashlib.md5(url.encode()).hexdigest(),
            "vector": vector.tolist(),
            "payload": {"url": url, "content": content}
        }]
    )
    return {"msg": "新内容已入库", "exists": False}

class SpiderRequest(BaseModel):
    url: str

@app.post("/fetch_content")
async def fetch_content_api(req: SpiderRequest):
    # 从配置读取 spider 服务地址
    spider_conf = config.get("sprider", {})
    spider_url = spider_conf.get("url")
    if not spider_url:
        return {"error": "未配置 spider.url"}
    # 调用外部抓取API
    try:
        resp = requests.post(
            spider_url.rstrip("/") + "/fetch",  # 假设对方API为 /fetch
            json={"url": req.url},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        # 假设返回格式为 {"content": "..."}
        return {"content": data.get("content", "")}
    except Exception as e:
        return {"error": f"抓取失败: {str(e)}"}

# 定时任务只负责调用 learning/fetch_and_learn.py 的 fetch_and_learn 方法
import sys
sys.path.append("./learning")

# 启动定时任务
spider_conf = config.get("sprider", {})
span_hours = int(spider_conf.get("span_hours", 24))
scheduler = BackgroundScheduler()

def fetch_and_learn_with_log():
    import datetime
    print(f"[定时任务] fetch_and_learn 开始执行: {datetime.datetime.now().isoformat()}")
    try:
        fetch_and_learn()
        print(f"[定时任务] fetch_and_learn 执行完成: {datetime.datetime.now().isoformat()}")
    except Exception as e:
        print(f"[定时任务] fetch_and_learn 执行异常: {e}")

@app.get("/docs_page", response_class=HTMLResponse)
def custom_docs_page():
    # 提供一个简单的前端页面入口，跳转到 FastAPI 的 Swagger UI
    return get_swagger_ui_html(openapi_url=app.openapi_url or "/openapi.json", title="xrole API 文档")

def run_audio2text_with_venv(material_dir: str):
    """
    用虚拟环境 python 路径调用 audio2text.py，确保依赖一致。
    """
    import subprocess
    import sys
    import os
    # 自动检测虚拟环境 python 路径
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        python_bin = os.path.join(venv, "bin", "python")
    else:
        python_bin = sys.executable
    script_path = os.path.join(os.path.dirname(__file__), "learning", "audio2text.py")
    if not os.path.exists(script_path):
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "learning", "audio2text.py"))
    print(f"[audio2text] 调用: {python_bin} {script_path} {material_dir}")
    try:
        subprocess.run([str(python_bin), str(script_path), str(material_dir)], check=True)
    except Exception as e:
        print(f"[audio2text] 调用失败: {e}")

@app.post("/api/import_materials")
async def import_materials_api(file: UploadFile = File(...)):
    """
    上传单个文件并自动导入知识库（embedding、去重、入库）。
    """
    import shutil
    material_dir = config.get("material_dir", "/data/xrole_materials")
    os.makedirs(material_dir, exist_ok=True)
    filename = file.filename or ""
    ext = os.path.splitext(filename)[-1].lower()
    if ext not in ALLOWED_EXTS or (file.content_type not in ALLOWED_MIME and not ext in [".doc", ".docx"]):
        return JSONResponse({"error": f"不支持的文件类型: {filename}"}, status_code=400)
    file_path = os.path.join(material_dir, filename or "uploaded_file")
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # 新增：如为音视频文件，自动调用 audio2text.py 和 video_ocr.py
    filename = file.filename or ""
    is_video = isinstance(filename, str) and filename.lower().endswith((".mp3", ".wav", ".mp4", ".m4a", ".avi", ".mov", ".mkv"))
    if is_video:
        run_audio2text_with_venv(material_dir)
        # 自动抽帧+OCR
        def run_video_ocr_with_venv(material_dir: str):
            import subprocess, sys, os
            venv = os.environ.get("VIRTUAL_ENV")
            if venv:
                python_bin = os.path.join(venv, "bin", "python")
            else:
                python_bin = sys.executable
            script_path = os.path.join(os.path.dirname(__file__), "learning", "video_ocr.py")
            if not os.path.exists(script_path):
                script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "learning", "video_ocr.py"))
            print(f"[video_ocr] 调用: {python_bin} {script_path} {material_dir}")
            try:
                subprocess.run([str(python_bin), str(script_path), str(material_dir), "5"], check=True)
            except Exception as e:
                print(f"[video_ocr] 调用失败: {e}")
        run_video_ocr_with_venv(material_dir)
    # 动态构造 embedding_models、embedder_dict、collections
    embedding_models = config.get("embedding_models")
    if not embedding_models:
        embedding_models = [{"name": "paraphrase-multilingual-MiniLM-L12-v2"}]
    from sentence_transformers import SentenceTransformer
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))
    embedder_dict = {}
    for m in embedding_models:
        model_name = m["name"]
        if not os.path.isabs(model_name):
            local_model_path = os.path.join(root_dir, "models", "sentence-transformers", model_name)
            local_model_path = os.path.abspath(local_model_path)
        else:
            local_model_path = model_name
        embedder_dict[model_name] = SentenceTransformer(local_model_path)  # 去掉 local_files_only 参数
    collections = config.get("collections")
    if not collections:
        collections = ["xrole_docs"]
    ensure_qdrant_collection(collections[0], vector_size=384)
    from learning.url_fingerprint import FingerprintDB
    fingerprint_db = FingerprintDB()
    try:
        import_materials(material_dir, embedder_dict, embedding_models, collections, fingerprint_db, qdrant_client)
        return JSONResponse({"msg": "文件已上传并导入知识库", "filename": file.filename})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# 挂载 Streamlit 前端静态文件（假设已用 streamlit run --browser.serverAddress 127.0.0.1 --server.headless true --server.runOnSave true --server.fileWatcherType none --server.port 8501 --server.enableCORS false --server.enableXsrfProtection false --server.baseUrl /admin 运行，或将前端静态文件打包到 static/admin）
# 这里假设将 streamlit_app.py 打包为静态HTML（如用 streamlit export），或用 streamlit-static 或 gradio-static 方案
# 你也可以用 npm build 的前端静态页面放到 static/admin

# 挂载静态目录
app.mount("/admin/static", StaticFiles(directory="static/admin"), name="admin-static")

@app.get("/admin", response_class=HTMLResponse)
def admin_index():
    # 返回管理界面首页（可用nginx反向代理 /admin 到此路由）
    with open("static/admin/index.html", encoding="utf-8") as f:
        return f.read()

@app.get("/admin/qdrant_points", response_class=JSONResponse)
def admin_qdrant_points(limit: int = 10, search: str = None):
    """
    管理员接口：查看 Qdrant 向量库部分内容（支持模糊搜索 url/content）。
    """
    try:
        # with_vectors=True 保证能看到向量维度
        result = qdrant_client.scroll(collection_name="xrole_docs", limit=100, with_vectors=True)  # 先查前100条
        points = []
        for p in result[0]:
            payload = p.payload or {}
            # 支持模糊搜索 url/content
            if search:
                if not (search in str(payload.get("url", "")) or search in str(payload.get("content", ""))):
                    continue
            points.append({
                "id": p.id,
                "payload": payload,
                "vector_dim": len(p.vector) if hasattr(p, 'vector') and p.vector is not None else (len(p.vector[0]) if hasattr(p, 'vector') and isinstance(p.vector, list) and len(p.vector) > 0 else None)
            })
            if len(points) >= limit:
                break
        return {"count": len(points), "points": points}
    except Exception as e:
        return {"error": str(e)}
