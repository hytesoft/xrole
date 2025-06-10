import json
import os
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

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
    payload: dict = {}

class SearchRequest(BaseModel):
    text: str
    top_k: int = 3

class SearchResponse(BaseModel):
    docs: list[str]

@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    vector = embedder.encode(req.text).tolist()
    return {"vector": vector}

@app.post("/upsert")
def upsert(req: UpsertRequest):
    vector = embedder.encode(req.text).tolist()
    qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=[{
            "id": None,
            "vector": vector,
            "payload": req.payload | {"content": req.text}
        }]
    )
    return {"msg": "ok"}

@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    vector = embedder.encode(req.text).tolist()
    result = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=req.top_k
    )
    docs = [hit.payload.get("content", "") for hit in result]
    return {"docs": docs}
