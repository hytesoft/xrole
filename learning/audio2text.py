import os
import sys
import whisper

# 获取音视频目录
if len(sys.argv) > 1:
    video_dir = sys.argv[1]
else:
    video_dir = os.environ.get("XROLE_MATERIAL_DIR", "/data/xrole_materials")

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
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(result["text"])
            print(f"已保存转写文本: {txt_path}")
        except Exception as e:
            print(f"转写失败: {audio_path}, 错误: {e}")
