# xmodel 向量服务 API 说明

本服务提供文本向量化与存储服务，支持多种文件格式，适用于知识库、语义检索等场景。

## 通用说明
- 所有接口均为 HTTP POST，数据格式为 JSON。
- 所有接口必须提供 `user_id` 以实现数据隔离。
- 默认支持的文件类型：
  - 纯文本 (text/plain)
  - Markdown文档 (text/markdown, text/x-markdown)
  - PDF (application/pdf)
  - Word文档 (.docx)

---

## 1. /upload（推荐使用）
**功能**：上传并处理文档（支持多种格式）

- URL：`/upload`
- 方法：POST
- 请求格式：`multipart/form-data`
- 参数：
  - `file`：文件内容（必填）
  - `user_id`：用户标识（必填）
  - `doc_id`：文档唯一标识（必填）
- 支持的文件类型：
  - 纯文本文件（.txt）
  - Markdown文件（.md, .markdown）
  - PDF文件（.pdf）
  - Word文档（.docx）
- 返回：
```json
{
  "success": true,
  "message": "文档已处理并存储,ID:doc123,共处理5个文本块"
}
```
- 注意事项：
  - 文件会被自动分块处理，每块最大500字符
  - 支持批量处理，每100个块自动上传一次
  - 纯文本文件需要使用UTF-8编码

## 2. /doc（低级接口）
**功能**：上传并处理文档的底层接口

> ⚠️ 注意：推荐使用更简单的 `/upload` 接口。这是一个低级接口，主要用于程序内部调用。

- URL：`/doc`
- 方法：POST
- 请求体：
```json
{
  "content": "二进制文件内容（注意：直接使用二进制内容，不要进行base64编码）",
  "content_type": "text/plain",  // 文件类型，支持 text/plain, text/markdown, text/x-markdown, application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document
  "user_id": "user123",  // 必填，用户标识
  "doc_id": "doc123"     // 可选，文档唯一标识，不传则自动生成
}
```
- 返回：
```json
{
  "success": true,
  "message": "文档已处理并存储,ID:doc123,共处理5个文本块"
}
```
- 注意事项：
  - 这是一个低级接口，需要手动处理二进制内容
  - 不要对二进制内容进行base64编码
  - 直接使用原始二进制数据
  - 对于大多数使用场景，建议使用 `/upload` 接口

## 3. /search
**功能**：搜索相似文本内容（语义检索）

- URL：`/search`
- 方法：POST
- 请求体：
```json
{
  "text": "要搜索的文本内容",
  "user_id": "user123",  // 必填，用户标识
  "top_k": 3             // 可选，返回最相似的条数，默认3条
}
```
- 返回：
```json
{
  "success": true,
  "results": [
    {
      "content": "找到的相似文本1",
      "score": 0.95
    },
    {
      "content": "找到的相似文本2",
      "score": 0.85
    },
    {
      "content": "找到的相似文本3",
      "score": 0.75
    }
  ]
}
```
- 注意事项：
  - 搜索文本长度不能超过500字符
  - 会返回用户自己上传的文档中最相似的内容
  - score 表示相似度得分（0-1之间，越大越相似）

## 4. /delete_doc
**功能**：删除指定文档的所有内容

- URL：`/delete_doc`
- 方法：POST
- 请求体：
```json
{
  "doc_id": "doc123",    // 文档ID
  "user_id": "user123"   // 必填，用户标识
}
```
- 返回：
```json
{
  "success": true,
  "message": "已删除文档 doc123 的所有内容"
}
```
- 注意事项：
  - 只能删除自己(user_id)的文档
  - 删除操作会删除该文档的所有文本块
  - 删除后不可恢复

## 5. /delete_user
**功能**：删除用户的所有数据

- URL：`/delete_user`
- 方法：POST
- 请求参数：
  - 直接在URL中传入 user_id
  - 例如：POST /delete_user?user_id=user123
- 返回：
```json
{
  "success": true,
  "message": "已删除用户 user123 的所有数据"
}
```
- 注意事项：
  - 此操作会删除该用户的所有文档和向量
  - 删除是异步操作
  - 删除后不可恢复

## 环境要求
- 需要设置以下环境变量：
  - `XMODEL_QDRANT_URL`：Qdrant服务地址
  - `XMODEL_QDRANT_API_KEY`：访问密钥
  - `XMODEL_VECTOR_SIZE`：向量维度（默认384）

## 典型使用流程
1. 上传文档：调用 `/doc` 接口
2. 获取向量：调用 `/text` 接口
3. 删除文档：调用 `/delete_doc` 接口
4. 清理用户数据：调用 `/delete_user` 接口

---

# 向量服务 API 文档

## 特性

- 支持多种文件格式的上传和处理
- 文本内容预处理确保安全性
  - JSON 格式标准化
  - 特殊字符处理
  - 换行符统一
  - 不可打印字符过滤
- 用户数据隔离
- 相似文本搜索
- 文档和用户数据管理

## API 接口

### 1. 文件上传接口

```http
POST /upload
```

使用标准的文件上传方式处理文档。

**请求参数:**
- `file`: 文件 (multipart/form-data)
- `user_id`: 用户ID (multipart/form-data)

**支持的文件类型:**
- 文本文件 (.txt)
- PDF文件 (.pdf)
- Word文档 (.docx)

**响应示例:**
```json
{
  "success": true,
  "message": "文档已处理并存储,ID:123456,共处理10个文本块"
}
```

### 2. 二进制文档上传

```http
POST /doc
```

用于直接上传二进制内容。

**请求体:**
```json
{
  "user_id": "string",
  "content": "string (base64编码的二进制内容)",
  "content_type": "string (MIME类型)"
}
```

### 3. 相似文本搜索

```http
POST /search
```

搜索相似的文本内容。

**请求体:**
```json
{
  "text": "string (要搜索的文本)",
  "user_id": "string",
  "limit": "number (可选,默认10)"
}
```

### 4. 删除文档

```http
DELETE /delete_doc
```

删除指定的文档。

**请求体:**
```json
{
  "doc_id": "string",
  "user_id": "string"
}
```

### 5. 删除用户数据

```http
DELETE /delete_user/{user_id}
```

删除指定用户的所有数据。

## 注意事项

1. 所有接口都需要提供 `user_id` 参数
2. 大文件建议分块上传
3. 文本内容会进行预处理以确保安全性：
   - 特殊字符会被适当转义
   - JSON格式会被标准化
   - 换行符会被统一处理
   - 不可打印字符会被过滤
4. 建议定期清理不再需要的数据
