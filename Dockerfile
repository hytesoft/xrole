# 基于官方 Python 镜像
FROM python:3.11-slim

# 使用国内 apt 源加速（以中科大为例，可换为阿里/清华等）
# 复制项目文件
COPY web_api.py /app/web_api.py
COPY requirements.txt /app/requirements.txt
COPY config /app/config
# 安装系统依赖（tesseract-ocr、ffmpeg、中文语言包等）
RUN pip3 install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r /app/requirements.txt
# 设置工作目录
WORKDIR /app


# 安装 Python 依赖


# 设置环境变量（如有需要）
ENV PYTHONUNBUFFERED=1

# 默认启动命令（可按需修改）
# 启动 web_api.py（FastAPI 主后端）和 streamlit_app.py（资料上传/管理前端）
CMD ["uvicorn", "web_api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
# 备注：
# - 已集成 tesseract-ocr（含中文）、ffmpeg，满足音视频转写和 OCR 需求。
# - requirements.txt 需包含 pytesseract、pillow、openai-whisper、ffmpeg-python 等。
# - 如需 PaddleOCR/EasyOCR，可在 requirements.txt 里加 paddleocr/easyocr。
# - 如需启动 FastAPI/Uvicorn，请将 CMD 改为 uvicorn 启动命令。
