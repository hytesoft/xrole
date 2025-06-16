# xmodel 向量服务 API 说明

本服务为极简文本向量化与 Qdrant 检索/存储 API，适用于知识库、语义检索、RAG 场景。

## 通用说明
- 所有接口均为 HTTP POST，数据格式为 JSON。
- 推荐通过 Docker 部署，模型目录挂载到 `/app/models`，Qdrant 地址通过环境变量配置。
- 支持多用户隔离（user_id 字段），支持内容精确删除与用户批量删除。

---

## 1. /embed
**功能**：将文本转为向量

- URL：`/embed`
- 方法：POST
- 请求体：
```json
{
  "text": "要转为向量的文本"
}
```
- 返回：
```json
{
  "vector": [0.123, 0.456, ...]
}
```

---

## 2. /upsert
**功能**：文本入库（向量化并存入 Qdrant）

- URL：`/upsert`
- 方法：POST
- 请求体：
```json
{
  "text": "要存储的文本",
  "user_id": "可选，用户唯一标识",
  "payload": {"filename": "a.txt", "tag": "可选自定义字段"}
}
```
- 返回：
```json
{"msg": "ok"}
```

---

## 3. /search
**功能**：语义检索，返回最相似的内容

- URL：`/search`
- 方法：POST
- 请求体：
```json
{
  "text": "要检索的文本",
  "user_id": "可选，传则只查该用户数据",
  "top_k": 3
}
```
- 返回：
```json
{
  "docs": ["最相似内容1", "最相似内容2", "最相似内容3"]
}
```

---

## 4. /delete
**功能**：删除指定内容（精确匹配）

- URL：`/delete`
- 方法：POST
- 请求体：
```json
{
  "text": "要删除的文本",
  "user_id": "可选"
}
```
- 返回：
```json
{"msg": "已删除 N 条数据"}
```

---

## 5. /delete_user
**功能**：删除该用户下所有内容

- URL：`/delete_user`
- 方法：POST
- 请求体：
```json
{
  "user_id": "用户唯一标识"
}
```
- 返回：
```json
{"msg": "已请求删除 user_id=xxx 下所有数据（异步，Qdrant 会自动处理）"}
```

---

## 环境变量与部署
- `XMODEL_QDRANT_URL`：Qdrant 服务地址
- `XMODEL_QDRANT_API_KEY`：Qdrant API 密钥
- `XMODEL_VECTOR_SIZE`：向量维度（默认384）
- 模型目录挂载到 `/app/models`

---

## 典型调用流程
1. `/embed` 获取向量（如需自定义处理）
2. `/upsert` 存入文本及向量
3. `/search` 检索最相似内容，可将结果拼接到 LLM prompt
4. `/delete` 精确删除某条内容
5. `/delete_user` 批量删除用户所有内容

---

如需批量、模糊、标签等高级功能可扩展，详见源码注释。
