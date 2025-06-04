import os
import json
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any
import requests

# 读取配置文件
def load_config(path: str = "config/xrole.conf") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

app = FastAPI(title="xrole 极简问答 API")

class QueryRequest(BaseModel):
    text: str

@app.post("/query")
async def query_api(req: QueryRequest):
    embed_url = config["embedding_api"]["url"]
    embed_resp = requests.post(embed_url, json={"text": req.text}, timeout=10)
    vector = embed_resp.json().get("vector", [])
    # 构造 prompt，调用 LLM
    llm_conf = config.get("llm", {})
    prompt = f"{config.get('prompt', '')}\n用户输入：{req.text}\n请给出专业解答："
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
        "answer": answer
    }
