FROM minideb:bookworm

# 使用清华源加速 apt 安装
RUN echo 'deb http://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free' > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y python3.11 python3.11-venv python3.11-distutils python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 && ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /app

COPY requirements.txt ./
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --break-system-packages --no-cache-dir -r requirements.txt

COPY infer.py ./

# 清理 PaddleSpeech 以外的缓存和无用模型，仅保留 conformer_wenetspeech
RUN find /root/.paddlespeech/models/ -mindepth 1 -maxdepth 1 ! -name 'conformer_wenetspeech*' -exec rm -rf {} + || true \
    && rm -rf /root/.cache ~/.cache /tmp/*

CMD ["python3", "-m", "uvicorn", "infer:app", "--host", "0.0.0.0", "--port", "8000"]