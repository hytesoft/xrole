import json
import os
from fastapi import FastAPI, Body
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.models import Distance, VectorParams
from typing import Optional

# 模型目录写死为 /model，部署时通过 Docker -v /your/model:/model 挂载
EMBED_MODEL_PATH = "/app/models"
QDRANT_URL = os.environ.get("XMODEL_QDRANT_URL")
QDRANT_API_KEY = os.environ.get("XMODEL_QDRANT_API_KEY")
VECTOR_SIZE = int(os.environ.get("XMODEL_VECTOR_SIZE", 384))
COLLECTION_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

if not QDRANT_URL:
    # 兜底读取 config.conf
    with open("config.conf", "r", encoding="utf-8") as f:
        config = json.load(f)
    model_conf = config["embedding_models"][0]
    # EMBED_MODEL_PATH = model_conf.get("dir") or model_conf["name"]  # 已写死
    qdrant_conf = config.get("qdrant", {})
    QDRANT_URL = qdrant_conf.get("url")
    QDRANT_API_KEY = qdrant_conf.get("api_key")
    VECTOR_SIZE = model_conf.get("dim", VECTOR_SIZE)
    COLLECTION_NAME = config.get("collection", COLLECTION_NAME)

embedder = SentenceTransformer(EMBED_MODEL_PATH)

# 初始化 Qdrant 客户端
qdrant_client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
    prefer_grpc=False,
    verify=False
)

def ensure_qdrant_collection():
    if not qdrant_client.collection_exists(COLLECTION_NAME):
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
        )

ensure_qdrant_collection()

app = FastAPI(title="Embedding API")

class EmbedRequest(BaseModel):
    text: str

class EmbedResponse(BaseModel):
    vector: list[float]

class UpsertRequest(BaseModel):
    text: str
    user_id: Optional[str] = None  # 可选
    payload: dict = {}

class SearchRequest(BaseModel):
    text: str
    user_id: Optional[str] = None  # 可选
    top_k: int = 3

class SearchResponse(BaseModel):
    docs: list[str]

class DeleteRequest(BaseModel):
    text: str
    user_id: Optional[str] = None

class DeleteUserRequest(BaseModel):
    user_id: str

@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    vector = embedder.encode(req.text).tolist()
    return {"vector": vector}

@app.post("/upsert")
def upsert(req: UpsertRequest):
    vector = embedder.encode(req.text).tolist()
    payload = {**req.payload, "content": req.text}
    if req.user_id:
        payload["user_id"] = req.user_id
    qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=[{
            "id": None,
            "vector": vector,
            "payload": payload
        }]
    )
    return {"msg": "ok"}

@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    vector = embedder.encode(req.text).tolist()
    filter_ = None
    if req.user_id:
        filter_ = {"must": [{"key": "user_id", "match": {"value": req.user_id}}]}
    result = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=req.top_k,
        filter=filter_
    )
    docs = [hit.payload.get("content", "") for hit in result]
    return {"docs": docs}

@app.post("/delete")
def delete(req: DeleteRequest):
    vector = embedder.encode(req.text).tolist()
    # 检索所有匹配 user_id 的向量，找到与该 vector 最近的点
    filter_ = None
    if req.user_id:
        filter_ = {"must": [{"key": "user_id", "match": {"value": req.user_id}}]}
    hits = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=10,
        filter=filter_
    )
    # 只删除与内容完全一致的点（防止误删）
    del_ids = [hit.id for hit in hits if hit.payload.get("content", "") == req.text]
    if del_ids:
        qdrant_client.delete(collection_name=COLLECTION_NAME, points_selector={"points": del_ids})
        return {"msg": f"已删除 {len(del_ids)} 条数据"}
    return {"msg": "未找到完全匹配的数据，无删除"}

@app.post("/delete_user")
def delete_user(req: DeleteUserRequest):
    if not req.user_id:
        return {"msg": "user_id 不能为空"}
    filter_ = {"must": [{"key": "user_id", "match": {"value": req.user_id}}]}
    points_selector = qmodels.FilterSelector(filter=qmodels.Filter(**filter_))
    qdrant_client.delete(collection_name=COLLECTION_NAME, points_selector=points_selector)
    return {"msg": f"已请求删除 user_id={req.user_id} 下所有数据（异步，Qdrant 会自动处理）"}
