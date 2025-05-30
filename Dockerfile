# 基于官方 Python 镜像
FROM python:3.11-slim

# 使用国内 apt 源加速（以中科大为例，可换为阿里/清华等）
RUN sed -i 's|http://deb.debian.org|https://mirrors.ustc.edu.cn|g' /etc/apt/sources.list

# 安装系统依赖（tesseract-ocr、ffmpeg、中文语言包等）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        ffmpeg \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 \
        && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY . /app

# 安装 Python 依赖
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 设置环境变量（如有需要）
ENV PYTHONUNBUFFERED=1

# 默认启动命令（可按需修改）
# 启动 web_api.py（FastAPI 主后端）和 streamlit_app.py（资料上传/管理前端）
CMD ["sh", "-c", "python web_api.py & streamlit run streamlit_app.py --server.port 8501 --server.headless true --server.enableCORS false --server.enableXsrfProtection false --server.fileWatcherType none --server.runOnSave true --browser.serverAddress 0.0.0.0"]

# 备注：
# - 已集成 tesseract-ocr（含中文）、ffmpeg，满足音视频转写和 OCR 需求。
# - requirements.txt 需包含 pytesseract、pillow、openai-whisper、ffmpeg-python 等。
# - 如需 PaddleOCR/EasyOCR，可在 requirements.txt 里加 paddleocr/easyocr。
# - 如需启动 FastAPI/Uvicorn，请将 CMD 改为 uvicorn 启动命令。
