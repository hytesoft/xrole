import json
import os
import sys
import glob
import subprocess
from PIL import Image
import pytesseract

def extract_frames(video_path: str, out_dir: str, interval: int = 5):
    """
    用 ffmpeg 每 interval 秒抽一帧，保存到 out_dir
    """
    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    # -vf fps=1/interval 表示每 interval 秒一帧
    cmd = [
        'ffmpeg', '-i', video_path,
        '-vf', f'fps=1/{interval}',
        '-q:v', '2',
        os.path.join(out_dir, '%04d.jpg')
    ]
    subprocess.run(cmd, check=True)

def ocr_image(image_path: str, lang: str = 'chi_sim') -> str:
    """
    用 tesseract OCR 识别图片文字
    """
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang=lang)
        return text.strip() if isinstance(text, str) else ''
    except Exception as e:
        print(f"[OCR] 识别失败: {image_path}, 错误: {e}")
        return ''

def video_to_ocr_txt(video_path: str, transcripts_dir: str, interval: int = 5, lang: str = 'chi_sim'):
    """
    对单个视频抽帧+OCR，输出到 transcripts/xxx.mp4.ocr.txt
    """
    video_name = os.path.basename(video_path)
    frame_dir = os.path.join(transcripts_dir, f"{video_name}_frames")
    extract_frames(video_path, frame_dir, interval=interval)
    txt_path = os.path.join(transcripts_dir, f"{video_name}.ocr.txt")
    with open(txt_path, 'w', encoding='utf-8') as fout:
        for jpg in sorted(glob.glob(os.path.join(frame_dir, '*.jpg'))):
            text = ocr_image(jpg, lang=lang)
            if text:
                fout.write(f"# {os.path.basename(jpg)}\n{text}\n\n")
    print(f"[video_ocr] 已保存: {txt_path}")
    # 可选：处理完后删除帧图片节省空间
    for jpg in glob.glob(os.path.join(frame_dir, '*.jpg')):
        os.remove(jpg)
    os.rmdir(frame_dir)

def ocr_image_file(image_path: str, lang: str = 'chi_sim'):
    """
    对单张图片做 OCR，输出 .ocr.txt 文件
    """
    text = ocr_image(image_path, lang=lang)
    if text:
        txt_path = image_path + '.ocr.txt'
        with open(txt_path, 'w', encoding='utf-8') as fout:
            fout.write(text + '\n')
        print(f"[img_ocr] 已保存: {txt_path}")
    else:
        print(f"[img_ocr] 无内容: {image_path}")


def batch_image_ocr(transcripts_dir: str, lang: str = 'chi_sim'):
    """
    递归扫描 transcripts_dir 下所有图片，做 OCR
    """
    img_exts = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
    for root, _, files in os.walk(transcripts_dir):
        for fname in files:
            if fname.lower().endswith(img_exts):
                img_path = os.path.join(root, fname)
                # 跳过已存在 ocr.txt 的图片
                if os.path.exists(img_path + '.ocr.txt'):
                    continue
                ocr_image_file(img_path, lang=lang)

def batch_video_ocr(material_dir: str, interval: int = 5, lang: str = 'chi_sim'):
    """
    批量处理 material_dir 下所有视频，并对 transcripts/ 下所有图片做 OCR
    """
    transcripts_dir = os.path.join(material_dir, 'transcripts')
    os.makedirs(transcripts_dir, exist_ok=True)
    for ext in ('.mp4', '.avi', '.mov', '.mkv'):
        for video_path in glob.glob(os.path.join(material_dir, f'*{ext}')):
            print(f"[video_ocr] 处理: {video_path}")
            try:
                video_to_ocr_txt(video_path, transcripts_dir, interval=interval, lang=lang)
            except Exception as e:
                print(f"[video_ocr] 失败: {video_path}, 错误: {e}")
    # 新增：对 transcripts/ 下所有图片做 OCR
    batch_image_ocr(transcripts_dir, lang=lang)

if __name__ == '__main__':
    # 用法: python video_ocr.py [material_dir] [interval]
    conf_path = os.path.join(os.path.dirname(__file__), '../config/xrole.conf')
    with open(conf_path, 'r', encoding='utf-8') as f:
        conf = json.load(f)
    root_dir = str(conf.get('root_dir', ''))
    material_dir_conf = str(conf.get('material_dir', 'data/role_materials'))
    if os.path.isabs(material_dir_conf):
        default_material_dir = material_dir_conf
    else:
        default_material_dir = os.path.join(root_dir, material_dir_conf)
    material_dir: str = str(sys.argv[1]) if len(sys.argv) > 1 else default_material_dir
    interval: int = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    batch_video_ocr(material_dir, interval=interval)
