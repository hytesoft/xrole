import os
import uuid
import time
import json
import re
from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from pydantic import BaseModel, field_validator
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from typing import Optional, List, Dict, Any, Generator
import PyPDF2
import docx
import io

# 常量定义
MAX_TEXT_LENGTH = 500  # 文本分块大小
OVERLAP_LENGTH = 100   # 重叠长度
MAX_RETRIES = 3       # 最大重试次数
RETRY_DELAY = 2       # 重试延迟（秒）

EMBED_MODEL_PATH = "/app/models"
#EMBED_MODEL_PATH = "/home/jj/docker/models/paraphrase-multilingual-MiniLM-L12-v2"
QDRANT_URL = os.environ.get("XMODEL_QDRANT_URL")
QDRANT_API_KEY = os.environ.get("XMODEL_QDRANT_API_KEY")
VECTOR_SIZE = int(os.environ.get("XMODEL_VECTOR_SIZE", 384))
COLLECTION_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

if not QDRANT_URL:
    raise ValueError("请设置 XMODEL_QDRANT_URL 环境变量")

# 初始化模型
embedder = SentenceTransformer(EMBED_MODEL_PATH)

def get_qdrant_client(max_retries=MAX_RETRIES):
    """创建Qdrant客户端并确保连接成功"""
    for attempt in range(max_retries):
        try:
            client = QdrantClient(
                url=QDRANT_URL,
                api_key=QDRANT_API_KEY,
                prefer_grpc=False,
                verify=False,
                timeout=5  # 5秒超时
            )
            # 测试连接
            client.get_collections()
            return client
        except (ResponseHandlingException, UnexpectedResponse) as e:
            if attempt == max_retries - 1:
                raise ValueError(f"无法连接到Qdrant服务器({QDRANT_URL}): {str(e)}")
            print(f"连接Qdrant失败,{RETRY_DELAY}秒后重试...")
            time.sleep(RETRY_DELAY)

# 初始化数据库连接
qdrant_client = get_qdrant_client()

# 确保集合存在
def ensure_qdrant_collection():
    """确保Qdrant集合存在，带重试机制"""
    for attempt in range(MAX_RETRIES):
        try:
            if not qdrant_client.collection_exists(COLLECTION_NAME):
                qdrant_client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
                )
            return
        except (ResponseHandlingException, UnexpectedResponse) as e:
            if attempt == MAX_RETRIES - 1:
                raise ValueError(f"无法创建Qdrant集合: {str(e)}")
            print(f"创建集合失败,{RETRY_DELAY}秒后重试...")
            time.sleep(RETRY_DELAY)

try:
    ensure_qdrant_collection()
except Exception as e:
    print(f"警告: Qdrant初始化失败: {str(e)}")

# FastAPI 应用
app = FastAPI(title="Embedding API")

# 请求/响应模型
class BinaryDocRequest(BaseModel):
    """二进制文档请求"""
    content: bytes
    content_type: str = "text/plain"  # 默认为纯文本
    user_id: str  # 用户ID,必填
    doc_id: Optional[str] = None  # 可选的文档ID

class SearchRequest(BaseModel):
    """相似文本搜索请求"""
    text: str
    user_id: str  # 用户ID,必填
    top_k: int = 3  # 返回结果数量
    
    @field_validator('text')
    @classmethod
    def validate_text_length(cls, v: str) -> str:
        if len(v) > MAX_TEXT_LENGTH:
            raise ValueError(f'文本长度不能超过 {MAX_TEXT_LENGTH} 个字符')
        return v

class SearchResult(BaseModel):
    """搜索结果项"""
    content: str
    score: float

class SearchResponse(BaseModel):
    """搜索响应"""
    success: bool
    results: List[SearchResult]

class DeleteRequest(BaseModel):
    """删除文档请求"""
    doc_id: str
    user_id: str  # 用户ID,必填

class DeleteResponse(BaseModel):
    """删除响应"""
    success: bool
    message: str

def split_text(text: str, max_length: int = MAX_TEXT_LENGTH, overlap: int = OVERLAP_LENGTH) -> Generator[str, None, None]:
    """
    智能分块：根据文本密度和语义完整性将长文本分割成小段
    
    策略：
    1. 优先在段落边界分割
    2. 其次在句子边界分割
    3. 考虑文本密度，避免过于稀疏或过于密集的块
    4. 保持适当重叠以维持上下文连贯性
    """
    
    def is_dense_text(text: str) -> bool:
        """判断文本是否密集（通过计算有效字符比例）"""
        if not text:
            return False
        # 计算实际字符（中文、英文、数字）的比例
        valid_chars = sum(1 for c in text if c.isalnum() or '\u4e00' <= c <= '\u9fff')
        return valid_chars / len(text) > 0.6  # 60%为阈值
    
    def find_best_split_point(text: str, start: int, end: int) -> int:
        """
        找到最佳分割点：
        1. 优先在段落边界（两个或更多换行符）
        2. 其次在句子边界（句号、问号、感叹号等）
        3. 最后在标点符号处
        """
        # 在指定范围内查找段落边界
        text_range = text[start:end]
        paragraph_break = text_range.find('\n\n')
        if paragraph_break != -1:
            return start + paragraph_break + 2
        
        # 查找句子边界
        sentence_breaks = [
            text_range.rfind('。'), 
            text_range.rfind('！'),
            text_range.rfind('？'),
            text_range.rfind('；'),
            text_range.rfind('\n')
        ]
        
        # 找到最后一个有效的句子边界
        valid_breaks = [b for b in sentence_breaks if b != -1]
        if valid_breaks:
            return start + max(valid_breaks) + 1
            
        # 如果没有找到合适的分割点，返回最大长度位置
        return end

    start = 0
    text_length = len(text)
    
    while start < text_length:
        if start + max_length >= text_length:
            # 处理最后一块
            remaining_text = text[start:]
            if remaining_text.strip():  # 确保不是空白
                yield remaining_text
            break
            
        # 寻找合适的分割点
        end = start + max_length
        split_point = find_best_split_point(text, start, end)
        
        # 获取当前块
        current_chunk = text[start:split_point]
        
        # 如果当前块文本密度过低，尝试扩展或合并
        if not is_dense_text(current_chunk) and split_point < text_length:
            # 向后查找更多文本直到达到合适的密度
            next_end = min(split_point + max_length//2, text_length)
            next_split = find_best_split_point(text, split_point, next_end)
            current_chunk = text[start:next_split]
            split_point = next_split
        
        if current_chunk.strip():  # 确保块不是空白
            yield current_chunk
        
        # 计算下一块的起始位置，确保适当重叠
        start = max(start + 1, split_point - overlap)
        
        # 确保不会卡在同一位置
        if start >= split_point:
            start = split_point

# 支持的文件类型和对应的处理函数
SUPPORTED_CONTENT_TYPES = {
    'text/plain': 'utf-8',
    'text/markdown': 'utf-8',  # Markdown文件作为纯文本处理
    'text/x-markdown': 'utf-8',  # 某些系统可能使用这个MIME类型
    'application/pdf': 'pdf',
    'application/msword': 'doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx'
}

def clean_text(text: str) -> str:
    """
    清理文本内容，移除无用字符
    
    1. 移除所有控制字符（包括换页符、制表符等）
    2. 统一空白字符（多个空格合并为一个）
    3. 只保留中文、英文、数字、基本标点
    4. 移除重复的换行符
    """
    # 移除控制字符，但保留基本换行
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    
    # 统一换行符
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 合并多个换行符
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    # 合并多个空格
    text = re.sub(r'[ \t]+', ' ', text)
    
    # 只保留有用字符：
    # - 中文字符 (0x4e00-0x9fff)
    # - 英文字母 (a-zA-Z)
    # - 数字 (0-9)
    # - 基本标点 (,.!?;:，。！？；：)
    # - 括号 ([{())}])
    # - 换行符和空格
    text = ''.join(char for char in text 
                  if char == '\n' 
                  or char == ' '
                  or char in ',.!?;:，。！？；：([{())}]'
                  or char.isalnum()
                  or ('\u4e00' <= char <= '\u9fff'))
    
    # 整理格式
    text = text.strip()
    
    return text

def extract_text_from_pdf(content: bytes) -> str:
    """从PDF文件提取文本"""
    try:
        pdf_file = io.BytesIO(content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text_parts = []
        for page in pdf_reader.pages:
            text = page.extract_text()
            # 清理提取的文本
            text = clean_text(text)
            if text.strip():  # 只添加非空文本
                text_parts.append(text)
        return "\n\n".join(text_parts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF解析失败: {str(e)}")

def extract_text_from_docx(content: bytes) -> str:
    """从DOCX文件提取文本"""
    try:
        doc_file = io.BytesIO(content)
        doc = docx.Document(doc_file)
        text_parts = []
        for paragraph in doc.paragraphs:
            text = paragraph.text
            # 清理提取的文本
            text = clean_text(text)
            if text.strip():  # 只添加非空文本
                text_parts.append(text)
        return "\n".join(text_parts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"DOCX解析失败: {str(e)}")

def preprocess_text(text: str) -> str:
    """
    预处理文本内容，确保安全性和一致性
    """
    try:
        # 清理文本
        text = clean_text(text)
        
        # 如果文本是JSON格式，保持其结构
        try:
            json_obj = json.loads(text)
            text = json.dumps(json_obj, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
            
        # 如果是空字符串，抛出异常
        if not text.strip():
            raise ValueError("处理后的文本为空")
            
        return text
        
    except Exception as e:
        raise ValueError(f"文本预处理失败: {str(e)}")

def extract_text_from_binary(content: bytes, content_type: str) -> str:
    """根据文件类型提取文本"""
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400, 
            detail=f"不支持的文件类型: {content_type}。支持的类型: {list(SUPPORTED_CONTENT_TYPES.keys())}"
        )
    
    file_type = SUPPORTED_CONTENT_TYPES[content_type]
    try:
        if file_type == 'utf-8':
            raw_text = content.decode('utf-8')
            # 添加文本预处理步骤
            return preprocess_text(raw_text)
        elif file_type == 'pdf':
            raw_text = extract_text_from_pdf(content)
            return preprocess_text(raw_text)
        elif file_type == 'docx':
            raw_text = extract_text_from_docx(content)
            return preprocess_text(raw_text)
        else:
            raise HTTPException(status_code=400, detail=f"暂不支持的文件类型: {content_type}")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码错误,请确保文本文件使用UTF-8编码")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件处理失败: {str(e)}")

@app.post("/doc", response_model=DeleteResponse)
async def upload_document(req: BinaryDocRequest):
    """上传并处理文档"""
    try:
        # 根据文件类型提取文本
        text = extract_text_from_binary(req.content, req.content_type)
        
        # 生成文档ID
        doc_id = req.doc_id or str(uuid.uuid4())
        
        # 分块处理
        chunks = list(split_text(text))
        batch_points = []
        
        # 处理每个文本块
        for i, chunk in enumerate(chunks):
            if not chunk.strip():  # 跳过空白块
                continue
                
            vector = embedder.encode(chunk).tolist()
            
            # 准备元数据
            payload = {
                "content": chunk,
                "doc_id": doc_id,
                "chunk_index": i,
                "content_type": req.content_type,
                "user_id": req.user_id
            }
                
            # 生成符合要求的 point_id (UUID格式)
            point_id = str(uuid.uuid4())
            batch_points.append(PointStruct(
                id=point_id,
                vector=vector,
                payload=payload
            ))
            
            # 每100个点批量上传一次
            if len(batch_points) >= 100:
                qdrant_client.upsert(collection_name=COLLECTION_NAME, points=batch_points)
                batch_points = []
        
        # 上传剩余的点
        if batch_points:
            qdrant_client.upsert(collection_name=COLLECTION_NAME, points=batch_points)
        
        return {
            "success": True, 
            "message": f"文档已处理并存储,ID:{doc_id},共处理{len(chunks)}个文本块"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search", response_model=SearchResponse)
async def search_similar(req: SearchRequest):
    """检索相似文本"""
    try:
        # 预处理查询文本
        query_text = preprocess_text(req.text)
        
        # 将查询文本向量化
        query_vector = embedder.encode(query_text).tolist()
        
        # 执行向量搜索
        search_results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=req.top_k,
            query_filter=qmodels.Filter(
                must=[qmodels.FieldCondition(
                    key="user_id",
                    match=qmodels.MatchValue(value=req.user_id)
                )]
            ) if req.user_id else None
        )
        
        # 整理返回结果
        results = []
        for hit in search_results:
            if hasattr(hit, 'payload') and hit.payload:
                content = hit.payload.get("content", "")
                score = float(hit.score) if hasattr(hit, 'score') else 0.0
                results.append(SearchResult(content=content, score=score))
        
        return {
            "success": True,
            "results": results
        }
    except Exception as e:
        print(f"搜索错误: {str(e)}")  # 添加错误日志
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/delete_doc", response_model=DeleteResponse)
async def delete_document(req: DeleteRequest):
    """删除指定文档"""
    try:
        # 构建过滤器(必须包含user_id和doc_id)
        filter_must = [
            qmodels.FieldCondition(
                key="doc_id",
                match=qmodels.MatchValue(value=req.doc_id)
            ),
            qmodels.FieldCondition(
                key="user_id",
                match=qmodels.MatchValue(value=req.user_id)
            )
        ]
            
        # 删除所有相关的向量
        points_selector = qmodels.FilterSelector(
            filter=qmodels.Filter(must=filter_must)
        )
        qdrant_client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=points_selector
        )
        return {"success": True, "message": f"已删除文档 {req.doc_id} 的所有内容"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/delete_user", response_model=DeleteResponse)
async def delete_user_data(user_id: str):
    """删除用户所有数据"""
    try:
        points_selector = qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[qmodels.FieldCondition(
                    key="user_id",
                    match=qmodels.MatchValue(value=user_id)
                )]
            )
        )
        qdrant_client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=points_selector
        )
        return {"success": True, "message": f"已删除用户 {user_id} 的所有数据"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload", response_model=DeleteResponse)
async def upload_file(
    file: UploadFile = File(...),  # 上传的文件
    user_id: str = Form(...),      # 使用Form确保正确处理multipart/form-data
    doc_id: Optional[str] = Form(None)  # 可选的文档ID
):
    """文件上传接口，支持多种格式"""
    try:
        # 读取文件内容
        content = await file.read()
        
        # 获取文件类型
        content_type = file.content_type
        if not content_type:
            # 根据文件扩展名推测类型
            if file.filename.endswith('.pdf'):
                content_type = 'application/pdf'
            elif file.filename.endswith('.docx'):
                content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            elif file.filename.endswith(('.md', '.markdown')):
                content_type = 'text/markdown'
            else:
                raise ValueError('不支持的文件类型')
        
        # 构造二进制文档请求
        doc_request = BinaryDocRequest(
            content=content,
            content_type=content_type,
            user_id=user_id,
            doc_id=doc_id
        )
        
        # 调用现有的文档处理接口
        return await upload_document(doc_request)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传处理失败: {str(e)}")
