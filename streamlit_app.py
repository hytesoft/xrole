import streamlit as st
import requests
import os
import json
import pandas as pd
from io import StringIO

API_BASE = "http://localhost:8000"  # web_api.py 启动的API地址

st.set_page_config(page_title="智能知识库一体化平台", layout="wide")
st.title("📚 智能知识库一体化平台")

# 1. 文件上传区
def upload_file():
    st.header("1. 资料上传（txt/pdf/md/ppt/word/音视频等）")
    uploaded_file = st.file_uploader("选择文件上传", type=["txt", "md", "pdf", "ppt", "pptx", "mp3", "wav", "mp4", "avi", "mov", "doc", "docx"])
    if uploaded_file is not None:
        files = {"file": (uploaded_file.name, uploaded_file, uploaded_file.type)}
        with st.spinner("正在上传并入库..."):
            resp = requests.post(f"{API_BASE}/api/import_materials", files=files)
        if resp.ok:
            st.success(f"文件 {uploaded_file.name} 已上传并入库！")
        else:
            st.error(f"上传失败: {resp.text}")

# 2. 检索问答区
def search_qa():
    st.header("2. 检索/问答")
    query = st.text_input("请输入您的问题：")
    top_k = st.slider("返回Top-K条相关内容", 1, 10, 3)
    if st.button("检索并问答") and query:
        with st.spinner("正在检索..."):
            resp = requests.post(f"{API_BASE}/query", json={"text": query, "top_k": top_k})
        if resp.ok:
            data = resp.json()
            st.write("**相关知识片段：**")
            for i, doc in enumerate(data.get("related_docs", [])):
                st.info(f"{i+1}. {doc}")
            st.write("**AI专业解答：**")
            st.success(data.get("answer", "无结果"))
        else:
            st.error(f"检索失败: {resp.text}")

# 3. 自动化测评区
def eval_qa():
    st.header("3. 自动化测评（上传标准问答对，批量评测知识库效果）")
    st.markdown("上传csv，格式：question,answer")
    eval_file = st.file_uploader("上传标准问答对", type=["csv"], key="eval")
    if eval_file is not None:
        df = pd.read_csv(eval_file)
        results = []
        for idx, row in df.iterrows():
            q = row["question"]
            std_ans = str(row["answer"]).strip()
            try:
                resp = requests.post(f"{API_BASE}/query", json={"text": q, "top_k": 3})
                ai_ans = resp.json().get("answer", "")
            except Exception as e:
                ai_ans = f"ERROR: {e}"
            # 简单准确率：AI答案包含标准答案关键字
            hit = std_ans in ai_ans
            results.append({"question": q, "标准答案": std_ans, "AI答案": ai_ans, "命中": hit})
        res_df = pd.DataFrame(results)
        st.dataframe(res_df)
        acc = res_df["命中"].mean()
        st.metric("Top-1命中率", f"{acc*100:.1f}%")
        st.download_button("下载测评结果CSV", res_df.to_csv(index=False), file_name="eval_result.csv")

# 4. 可视化对比区
def visualize():
    st.header("4. 效果可视化对比")
    st.markdown("可上传多组测评结果csv，自动对比命中率等指标")
    files = st.file_uploader("上传多组测评结果csv", type=["csv"], accept_multiple_files=True, key="viz")
    if files:
        accs = []
        for f in files:
            df = pd.read_csv(f)
            acc = df["命中"].mean()
            accs.append({"文件": f.name, "命中率": acc})
        acc_df = pd.DataFrame(accs)
        st.bar_chart(acc_df.set_index("文件"))
        st.dataframe(acc_df)

with st.sidebar:
    st.image("https://img.shields.io/badge/xrole-AI--RAG--QA-blue?logo=github")
    st.markdown("[项目文档](https://github.com/) | [API接口文档](/docs_page)")

upload_file()
search_qa()
eval_qa()
visualize()
