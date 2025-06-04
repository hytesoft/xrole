FROM python:3.11-slim
WORKDIR /app
COPY embed_api.py /app/embed_api.py
COPY config.conf /app/config.conf
COPY requirements.txt /app/requirements.txt
# 建议将模型目录挂载到容器或COPY进来，示例：
# COPY models/paraphrase-multilingual-MiniLM-L12-v2 /app/model_dir
RUN pip3 install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r /app/requirements.txt
CMD ["uvicorn", "embed_api:app", "--host", "0.0.0.0", "--port", "8001"]
