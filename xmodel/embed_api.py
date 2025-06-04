import json
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

# 读取配置
with open("config.conf", "r", encoding="utf-8") as f:
    config = json.load(f)
model_conf = config["embedding_models"][0]
model_path = model_conf.get("dir") or model_conf["name"]
embedder = SentenceTransformer(model_path)

# 初始化 Qdrant 客户端
qdrant_conf = config.get("qdrant", {})
qdrant_client = QdrantClient(
    url=qdrant_conf.get("url"),
    api_key=qdrant_conf.get("api_key"),
    prefer_grpc=False,
    verify=False
)

COLLECTION_NAME = "xrole_docs"
VECTOR_SIZE = 384  # 视你的 embedding 维度而定

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
