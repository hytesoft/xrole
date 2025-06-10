import os
import json
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any
import requests

# 优先从环境变量读取配置
# 支持的环境变量：
#   XROLE_PROMPT                —— 业务 prompt
#   XROLE_LLM_MODEL             —— LLM 模型名
#   XROLE_LLM_BASE_URL          —— LLM API 地址
#   XROLE_LLM_API_KEY           —— LLM API 密钥
#   XROLE_EMBEDDING_API_URL     —— embedding 服务 API 地址
#   XROLE_ROLE_ID               —— 角色唯一标识（如用于消息队列分组等）
# 若未设置环境变量，则自动回退到 config/xrole.conf 配置文件

def load_config():
    config = {}
    config["role_id"] = os.environ.get("XROLE_ROLE_ID", "")
    # 支持 prompt、llm、embedding_api.url 从环境变量读取
    config["prompt"] = os.environ.get("XROLE_PROMPT", "")
    config["llm"] = {
        "model": os.environ.get("XROLE_LLM_MODEL", ""),
        "base_url": os.environ.get("XROLE_LLM_BASE_URL", ""),
        "api_key": os.environ.get("XROLE_LLM_API_KEY", "")
    }
    config["embedding_api"] = {
        "url": os.environ.get("XROLE_EMBEDDING_API_URL", "")
    }
    # 如果环境变量没配，尝试从 config/xrole.conf 兜底
    if not config["prompt"] or not config["llm"]["base_url"] or not config["embedding_api"]["url"]:
        try:
            with open("config/xrole.conf", "r", encoding="utf-8") as f:
                file_config = json.load(f)
            config = {**file_config, **config}
        except Exception:
            pass
    return config

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
    system_prompt = config.get('prompt', '')
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": req.text}
    ]
    llm_resp = requests.post(
        llm_conf.get("base_url"),
        headers={"Authorization": f"Bearer {llm_conf.get('api_key', '')}"},
        json={
            "model": llm_conf.get("model"),
            "messages": messages
        },
        timeout=30
    )
    answer = llm_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "无结果")
    return {
        "input": req.text,
        "answer": answer
    }
