import os
import sys
import whisper
import json
from pathlib import Path

# 获取 config 路径
conf_path = os.path.join(os.path.dirname(__file__), '../config/xrole.conf')
with open(conf_path, 'r', encoding='utf-8') as f:
    conf = json.load(f)
root_dir = conf.get('root_dir', '')
material_dir_conf = conf.get('material_dir', 'data/role_materials')
if os.path.isabs(material_dir_conf):
    material_dir = material_dir_conf
else:
    material_dir = str(Path(root_dir) / material_dir_conf)

# 获取音视频目录
if len(sys.argv) > 1:
    video_dir = str(sys.argv[1])
else:
    video_dir = material_dir

output_dir = os.path.join(video_dir, "transcripts")
os.makedirs(output_dir, exist_ok=True)

model = whisper.load_model("base")  # 可选 tiny/base/small/medium/large

for fname in os.listdir(video_dir):
    if fname.lower().endswith((".mp3", ".wav", ".mp4", ".m4a", ".avi", ".mov")):
        audio_path = os.path.join(video_dir, fname)
        print(f"正在转写: {audio_path}")
        try:
            result = model.transcribe(audio_path, language="zh")
            txt_path = os.path.join(output_dir, fname + ".txt")
            text = result.get("text", "")
            if not isinstance(text, str):
                text = "".join([str(t) for t in text])
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"已保存转写文本: {txt_path}")
        except Exception as e:
            print(f"转写失败: {audio_path}, 错误: {e}")
            # 新增详细日志
            with open(os.path.join(output_dir, "transcribe_error.log"), "a", encoding="utf-8") as logf:
                logf.write(f"转写失败: {audio_path}, 错误: {e}\n")
