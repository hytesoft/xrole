from fastapi import FastAPI, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from paddlespeech.cli.asr.infer import ASRExecutor
import shutil
import os
import uuid
import ffmpeg
import codecs

app = FastAPI()

asr = ASRExecutor()

UPLOAD_DIR = "audio"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 训练数据存储目录（全部用相对路径，避免权限问题）
TRAIN_AUDIO_DIR = "train_data/audio"
TRAIN_LABELS_PATH = "train_data/labels.tsv"
TRAIN_PROGRESS_PATH = "train_data/progress.txt"
os.makedirs(TRAIN_AUDIO_DIR, exist_ok=True)
os.makedirs("train_data", exist_ok=True)

TRAIN_TEXTS_PATH = "train_texts.txt"

# 获取下一条待朗读的句子
@app.get("/next_train_text/")
def next_train_text():
    # 读取题库
    with open(TRAIN_TEXTS_PATH, "r", encoding="utf-8") as f:
        texts = [line.strip() for line in f if line.strip()]
    # 读取进度
    idx = 0
    if os.path.exists(TRAIN_PROGRESS_PATH):
        with open(TRAIN_PROGRESS_PATH, "r", encoding="utf-8") as f:
            idx = int(f.read().strip() or 0)
    if idx >= len(texts):
        return {"text": None, "msg": "已完成全部题目"}
    return {"text": texts[idx], "idx": idx+1, "total": len(texts)}

# 上传录音并自动配对当前题目
@app.post("/upload_train_audio/")
async def upload_train_audio(file: UploadFile = File(...)):
    # 读取题库和进度
    with open(TRAIN_TEXTS_PATH, "r", encoding="utf-8") as f:
        texts = [line.strip() for line in f if line.strip()]
    idx = 0
    if os.path.exists(TRAIN_PROGRESS_PATH):
        with open(TRAIN_PROGRESS_PATH, "r", encoding="utf-8") as f:
            idx = int(f.read().strip() or 0)
    if idx >= len(texts):
        return {"msg": "已完成全部题目，无需再上传"}
    text = texts[idx]
    # 保存音频
    ext = os.path.splitext(file.filename)[-1]
    audio_id = f"{uuid.uuid4().hex}{ext}"
    audio_path = os.path.join(TRAIN_AUDIO_DIR, audio_id)
    with open(audio_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # 记录音频和文本对应关系
    with open(TRAIN_LABELS_PATH, "a", encoding="utf-8") as f:
        f.write(f"{audio_id}\t{text}\n")
    # 更新进度
    with open(TRAIN_PROGRESS_PATH, "w", encoding="utf-8") as f:
        f.write(str(idx+1))
    return {"msg": "训练数据已保存", "audio": audio_id, "text": text, "next_idx": idx+2, "total": len(texts)}

def convert_wav(input_path, output_path):
    (
        ffmpeg
        .input(input_path)
        .output(output_path, ar=16000, ac=1, format='wav', audio_bitrate='16k')
        .overwrite_output()
        .run(quiet=True)
    )

def load_hotwords(path="hotwords.txt"):
    hotwords = []
    if os.path.exists(path):
        with codecs.open(path, "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip()
                if word and not word.startswith('#'):
                    hotwords.append(word)
    return hotwords

def autocorrect(text):
    # 常见音译错词→正确词映射，可自行扩展
    corrections = {
        "开恩铺": "input",
        "泰克斯艾瑞": "textarea",
        "输入狂": "输入框",
        "派森": "python",
        "法斯特艾皮艾": "fastapi",
        "帕德尔斯皮奇": "paddlespeech",
        "艾艾": "AI",
        "艾皮艾": "API",
        "杰森": "json",
        "西艾斯艾斯": "CSS",
        "艾奇提艾姆艾尔": "HTML",
        # 可继续补充
    }
    for wrong, right in corrections.items():
        text = text.replace(wrong, right)
    return text

@app.post("/asr/")
async def asr_api(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[-1]
    temp_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}{ext}")
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # 自动转码为16k单声道wav
    converted_path = temp_path.replace(ext, "_16k.wav")
    convert_wav(temp_path, converted_path)
    # 加载热词
    hotwords = load_hotwords()
    hotword_str = ",".join(hotwords) if hotwords else None
    try:
        # 兼容 hotword 参数（1.5.0 及以上支持）
        import inspect
        asr_args = inspect.signature(asr.__call__).parameters
        if "hotword" in asr_args and hotword_str:
            result = asr(audio_file=converted_path, model='conformer_wenetspeech', lang='zh', hotword=hotword_str)
        else:
            result = asr(audio_file=converted_path, model='conformer_wenetspeech', lang='zh')
        result = autocorrect(result)  # 自动纠错
    except Exception as e:
        result = f"Error: {e}"
    os.remove(temp_path)
    os.remove(converted_path)
    return {"result": result}

# 新增：自定义文本采集接口，支持直接文本+音频上传
@app.post("/upload_train_data/")
async def upload_train_data(file: UploadFile = File(...), text: str = Form(...)):
    ext = os.path.splitext(file.filename)[-1]
    audio_id = f"{uuid.uuid4().hex}{ext}"
    audio_path = os.path.join(TRAIN_AUDIO_DIR, audio_id)
    temp_path = audio_path + ".tmp"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # 自动转码为16k单声道wav
    convert_wav(temp_path, audio_path)
    os.remove(temp_path)
    with open(TRAIN_LABELS_PATH, "a", encoding="utf-8") as f:
        f.write(f"{audio_id}\t{text}\n")
    return {"msg": "训练数据已保存", "audio": audio_id, "text": text}

# 路由全部注册完毕后再挂载静态文件
app.mount("/", StaticFiles(directory=".", html=True), name="static")