import os
import json
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any
import requests
import threading
import pika

# 优先从环境变量读取配置
# 支持的环境变量：
#   XROLE_PROMPT                —— 业务 prompt
#   XROLE_LLM_MODEL             —— LLM 模型名
#   XROLE_LLM_BASE_URL          —— LLM API 地址
#   XROLE_LLM_API_KEY           —— LLM API 密钥
#   XROLE_EMBEDDING_API_URL     —— embedding 服务 API 地址
#   XROLE_ROLE_ID               —— 角色唯一标识（如用于消息队列分组等）
#   XROLE_MQ_HOST               —— RabbitMQ 主机
#   XROLE_MQ_USER               —— RabbitMQ 用户
#   XROLE_MQ_PASS               —— RabbitMQ 密码
#   XROLE_MQ_QUEUE              —— RabbitMQ 队列
#   XROLE_MQ_REPLY_QUEUE        —— RabbitMQ 回写队列
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

def rabbitmq_consumer():
    mq_host = os.environ.get("XROLE_MQ_HOST", "localhost")
    mq_user = os.environ.get("XROLE_MQ_USER", "guest")
    mq_pass = os.environ.get("XROLE_MQ_PASS", "guest")
    mq_queue = os.environ.get("XROLE_MQ_QUEUE", f"role_queue_{config['role_id']}")
    credentials = pika.PlainCredentials(mq_user, mq_pass)
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=mq_host, credentials=credentials))
    channel = connection.channel()
    channel.queue_declare(queue=mq_queue, durable=True)

    def callback(ch, method, properties, body):
        import json
        try:
            msg = json.loads(body)
            # 假设消息内容为 {'content': 'xxx'}
            text = msg.get('content', '')
            # 复用 query_api 逻辑
            embed_url = config["embedding_api"]["url"]
            embed_resp = requests.post(embed_url, json={"text": text}, timeout=10)
            vector = embed_resp.json().get("vector", [])
            llm_conf = config.get("llm", {})
            prompt = f"{config.get('prompt', '')}\n用户输入：{text}\n请给出专业解答："
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
            # 回写结果到消息队列（可自定义回写队列名）
            reply_queue = os.environ.get("XROLE_MQ_REPLY_QUEUE", mq_queue)  # 默认回写到同一队列
            reply_msg = json.dumps({"content": text, "answer": answer}, ensure_ascii=False)
            channel.basic_publish(
                exchange='',
                routing_key=reply_queue,
                body=reply_msg.encode('utf-8'),
                properties=pika.BasicProperties(delivery_mode=2)  # 持久化
            )
            print(f"[MQ][{config['role_id']}] 收到: {text}，回复: {answer}，已回写队列: {reply_queue}")
        except Exception as e:
            print(f"[MQ][{config['role_id']}] 处理消息异常: {e}")
        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=mq_queue, on_message_callback=callback)
    print(f"[MQ][{config['role_id']}] 开始监听队列: {mq_queue}")
    channel.start_consuming()

def start_rabbitmq_listener():
    t = threading.Thread(target=rabbitmq_consumer, daemon=True)
    t.start()

start_rabbitmq_listener()
