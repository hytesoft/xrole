from fastapi import FastAPI, Request, UploadFile, File
from pydantic import BaseModel
from typing import Any, Dict
import json
import uvicorn
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
import requests
import hashlib
import os
import numpy as np
from learning.url_fingerprint import FingerprintDB
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
import shutil
from learning.fetch_and_learn import fetch_and_learn, import_materials
from fastapi.staticfiles import StaticFiles

# 读取配置文件
def load_config(path: str = "config/xrole.conf") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# 初始化 Qdrant 客户端
qdrant_conf = config.get("qdrant", {})
qdrant_client = QdrantClient(
    url=qdrant_conf.get("url"),
    api_key=qdrant_conf.get("api_key")
)

# 初始化向量模型（可根据实际情况更换模型名）
embedder = SentenceTransformer("/home/jj/docker/src/xrole/models/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", local_files_only=True)

app = FastAPI(title="xrole 智能助手 API")



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

# 启动时立即执行一次
fetch_and_learn_with_log()

scheduler.add_job(fetch_and_learn_with_log, 'interval', hours=span_hours, next_run_time=None)
scheduler.start()

@app.get("/docs_page", response_class=HTMLResponse)
def custom_docs_page():
    # 提供一个简单的前端页面入口，跳转到 FastAPI 的 Swagger UI
    return get_swagger_ui_html(openapi_url=app.openapi_url or "/openapi.json", title="xrole API 文档")

@app.post("/api/import_materials")
async def import_materials_api(file: UploadFile = File(...)):
    """
    上传单个文件并自动导入知识库（embedding、去重、入库）。
    """
    # 保存到 material_dir
    material_dir = config.get("material_dir", "/data/xrole_materials")
    os.makedirs(material_dir, exist_ok=True)
    file_path = os.path.join(material_dir, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # 动态构造 embedding_models、embedder_dict、collections
    embedding_models = config.get("embedding_models")
    if not embedding_models:
        embedding_models = [{"name": "paraphrase-multilingual-MiniLM-L12-v2"}]
    from sentence_transformers import SentenceTransformer
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    embedder_dict = {}
    for m in embedding_models:
        model_name = m["name"]
        if not os.path.isabs(model_name):
            local_model_path = os.path.join(root_dir, "models", "sentence-transformers", model_name)
            local_model_path = os.path.abspath(local_model_path)
        else:
            local_model_path = model_name
        embedder_dict[model_name] = SentenceTransformer(local_model_path, local_files_only=True)
    collections = config.get("collections")
    if not collections:
        collections = ["xrole_docs"]
    from learning.url_fingerprint import FingerprintDB
    fingerprint_db = FingerprintDB()
    from qdrant_client import QdrantClient
    qdrant_conf = config.get("qdrant", {})
    qdrant_client = QdrantClient(
        url=qdrant_conf.get("url"),
        api_key=qdrant_conf.get("api_key")
    )
    # 只处理上传的单个文件
    try:
        import_materials(material_dir, embedder_dict, embedding_models, collections, fingerprint_db, qdrant_client)
        return JSONResponse({"msg": "文件已上传并导入知识库", "filename": file.filename})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# 挂载 Streamlit 前端静态文件（假设已用 streamlit run --browser.serverAddress 127.0.0.1 --server.headless true --server.runOnSave true --server.fileWatcherType none --server.port 8501 --server.enableCORS false --server.enableXsrfProtection false --server.baseUrlPath /admin 运行，或将前端静态文件打包到 static/admin）
# 这里假设将 streamlit_app.py 打包为静态HTML（如用 streamlit export），或用 streamlit-static 或 gradio-static 方案
# 你也可以用 npm build 的前端静态页面放到 static/admin

# 挂载静态目录
app.mount("/admin/static", StaticFiles(directory="static/admin"), name="admin-static")

@app.get("/admin", response_class=HTMLResponse)
def admin_index():
    # 返回管理界面首页（可用nginx反向代理 /admin 到此路由）
    with open("static/admin/index.html", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
