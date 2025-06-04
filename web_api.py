import os
import json
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from sentence_transformers import SentenceTransformer
import requests

# 读取配置文件
def load_config(path: str = "config/xrole.conf") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# 初始化 Qdrant 客户端
qdrant_conf = config.get("qdrant", {})
qdrant_client = QdrantClient(
    url=qdrant_conf.get("url"),
    api_key=qdrant_conf.get("api_key"),
    prefer_grpc=False,
    verify=False
)

# 确保 collection 存在
def ensure_qdrant_collection(collection_name, vector_size=384):
    if not qdrant_client.collection_exists(collection_name):
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
        )

# 加载 embedding 模型
embedding_models = config.get("embedding_models")
if not embedding_models:
    embedding_models = [{"name": "paraphrase-multilingual-MiniLM-L12-v2"}]
model_name = embedding_models[0]["name"]
root_dir = os.path.abspath(os.path.dirname(__file__))
if not os.path.isabs(model_name):
    local_model_path = os.path.join(root_dir, "models", "sentence-transformers", model_name)
else:
    local_model_path = model_name
embedder = SentenceTransformer(local_model_path)

app = FastAPI(title="xrole 极简问答 API")

class QueryRequest(BaseModel):
    text: str
    top_k: int = 3

@app.post("/query")
async def query_api(req: QueryRequest):
    # 文本转向量
    vector = embedder.encode(req.text).tolist()
    # Qdrant 检索
    search_result = qdrant_client.search(
        collection_name="xrole_docs",
        query_vector=vector,
        limit=req.top_k
    )
    docs = [hit.payload.get("content", "") for hit in search_result]
    # 构造 prompt，调用大模型
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
