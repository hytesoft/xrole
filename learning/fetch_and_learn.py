import json
import requests
import hashlib
import numpy as np
from learning.url_fingerprint import FingerprintDB
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
import logging
import time
import os

def cosine_sim(a, b):
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

# 日志配置
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
log_dir = os.path.join(root_dir, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'fetch_and_learn.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def notify_exception(msg):
    # 这里可扩展为邮件/钉钉/企业微信等通知
    logging.error(f"[异常通知] {msg}")
    # 可扩展：os.system('curl ...')

def fetch_and_learn(config_path="config/xrole.conf", weblist_path="config/weblists.json"):
    # 读取配置
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        notify_exception(f"读取配置失败: {e}")
        return
    # 先获取当前 prompt 和 weblists
    prompt = config.get("prompt", "")
    try:
        with open(weblist_path, "r", encoding="utf-8") as f:
            weblists_data = json.load(f)
            weblists = weblists_data["weblists"]
    except Exception as e:
        notify_exception(f"读取 weblists.json 失败: {e}")
        return
    # 组织大模型输入
    current_urls = [item["url"] for item in weblists]
    llm_input = f"{prompt}\n\n为了保持该角色的学习能力，需要抓取哪些专业网站或数据源？当前已抓取资源有：{current_urls}。请以JSON数组格式返回建议的下载资源列表（每项为url和简要说明），如：[{{'url': '...', 'desc': '...'}}, ...]。只返回JSON数组，不要多余解释。"
    llm_conf = config.get("llm", {})
    try:
        resp = requests.post(
            llm_conf.get("base_url"),
            headers={"Authorization": f"Bearer {llm_conf.get('api_key', '')}"},
            json={
                "model": llm_conf.get("model"),
                "messages": [{"role": "user", "content": llm_input}]
            },
            timeout=60
        )
        llm_text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        print(llm_text)
        # 尝试解析大模型返回的JSON数组
        import re
        import ast
        match = re.search(r'\[.*\]', llm_text, re.DOTALL)
        if match:
            new_weblists = ast.literal_eval(match.group(0))
            # 兼容格式，补全 desc 字段
            for item in new_weblists:
                if "desc" not in item:
                    item["desc"] = ""
            # 更新 weblists.json
            with open(weblist_path, "w", encoding="utf-8") as f:
                json.dump({"weblists": new_weblists}, f, ensure_ascii=False, indent=2)
            logging.info(f"已根据大模型建议更新 weblists.json，资源数: {len(new_weblists)}")
            weblists = new_weblists
        else:
            logging.warning("大模型未返回有效的资源列表，继续用原有 weblists")
    except Exception as e:
        notify_exception(f"大模型生成资源列表失败: {e}")
    # 支持多 embedding 模型
    embedding_models = config.get("embedding_models")
    if not embedding_models:
        # 兼容老配置
        embedding_models = [{"name": "paraphrase-multilingual-MiniLM-L12-v2"}]
    embedder_dict = {}
    for m in embedding_models:
        model_name = m["name"]
        try:
            embedder_dict[model_name] = SentenceTransformer(model_name)
        except Exception as e:
            notify_exception(f"加载 embedding 模型 {model_name} 失败: {e}")
    # collection 支持
    collections = config.get("collections")
    if not collections:
        collections = ["xrole_docs"]
    # 初始化依赖
    fingerprint_db = FingerprintDB()
    qdrant_conf = config.get("qdrant", {})
    qdrant_client = QdrantClient(
        url=qdrant_conf.get("url"),
        api_key=qdrant_conf.get("api_key")
    )
    # 读取 weblists.json 和大模型推荐后，再获取 spider_url
    spider_conf = config.get("sprider", {})
    spider_url = spider_conf.get("url")
    if not spider_url:
        logging.warning("未配置 spider.url，跳过抓取")
        return
    # 步骤1：遍历 weblists，抓取A，指纹比对
    for item in weblists:
        url = item["url"]
        try:
            resp = requests.post(spider_url.rstrip("/") + "/fetch", json={"url": url}, timeout=30, verify=False)
            resp.raise_for_status()
            content_a = resp.json().get("content", "")
            if not content_a:
                logging.warning(f"{url} 抓取无内容（A阶段）")
                continue
            model_name = item.get("embedding_model") or embedding_models[0]["name"]
            embedder = embedder_dict.get(model_name)
            if not embedder:
                logging.error(f"未找到 embedding 模型 {model_name}，跳过 {url}")
                continue
            vector_a = embedder.encode(content_a)
            exists = False
            for _, fp in fingerprint_db.get_all_fingerprints():
                if cosine_sim(vector_a, fp) > 0.95:
                    exists = True
                    break
            if exists:
                logging.info(f"{url} 内容A已存在，跳过")
                continue
            # 步骤2：A为新内容，发给大模型让其抽取url列表
            llm_input2 = f"{prompt}\n\n请从以下内容中提取所有有价值的资源url，按时间顺序输出JSON数组（如: ['url1', 'url2', ...]），只返回数组，不要解释。内容：{content_a[:1000]}..."
            try:
                resp2 = requests.post(
                    llm_conf.get("base_url"),
                    headers={"Authorization": f"Bearer {llm_conf.get('api_key', '')}"},
                    json={
                        "model": llm_conf.get("model"),
                        "messages": [{"role": "user", "content": llm_input2}]
                    },
                    timeout=60
                )
                llm_text2 = resp2.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                import re
                import ast
                match2 = re.search(r'\[.*\]', llm_text2, re.DOTALL)
                if match2:
                    url_list = ast.literal_eval(match2.group(0))
                    logging.info(f"大模型抽取到{len(url_list)}个url，准备抓取B阶段")
                else:
                    logging.warning(f"大模型未返回有效url列表，跳过 {url}")
                    continue
                # 步骤3：遍历大模型返回的url列表，逐个抓取B，指纹比对，遇到老数据提前终止
                for b_url in url_list:
                    try:
                        resp_b = requests.post(spider_url.rstrip("/") + "/fetch", json={"url": b_url}, timeout=30, verify=False)
                        resp_b.raise_for_status()
                        content_b = resp_b.json().get("content", "")
                        if not content_b:
                            logging.warning(f"{b_url} 抓取无内容（B阶段）")
                            continue
                        vector_b = embedder.encode(content_b)
                        exists_b = False
                        for _, fp in fingerprint_db.get_all_fingerprints():
                            if cosine_sim(vector_b, fp) > 0.95:
                                exists_b = True
                                break
                        if exists_b:
                            logging.info(f"{b_url} 内容B已存在，后续url跳过")
                            break  # 按时间顺序，遇到老数据提前终止
                        # 新内容，入库
                        fingerprint_db.add_fingerprint(b_url, vector_b)
                        qdrant_client.upsert(
                            collection_name=item.get("collection") or collections[0],
                            points=[{
                                "id": hashlib.md5(b_url.encode()).hexdigest(),
                                "vector": vector_b.tolist(),
                                "payload": {"url": b_url, "content": content_b, "embedding_model": model_name}
                            }]
                        )
                        logging.info(f"{b_url} 新内容已入库 [模型:{model_name} 集合:{item.get('collection') or collections[0]}]")
                    except Exception as e:
                        logging.error(f"{b_url} B阶段抓取或入库失败: {e}")
            except Exception as e:
                notify_exception(f"大模型抽取url失败: {e}")
        except Exception as e:
            logging.error(f"{url} A阶段抓取或大模型处理失败: {e}")
