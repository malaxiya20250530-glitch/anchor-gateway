# 觉察推理与开源框架集成指南

## 策略：不改框架，加代理层

所有主流推理框架都支持 OpenAI 兼容 API。因此不需要修改任何框架代码——在 API 前面放一个代理即可。

```
User → ObserverProxy → Ollama/vLLM/TGI/LiteLLM/OpenAI
         │
         ├─ 流式读取 SSE chunk
         ├─ 累积到语义边界
         ├─ 运行观察器
         └─ 决定: 放行 / 标记 / 中断
```

## 已实现

`observer_proxy.py` 中的 `ObserverProxy` 类可以直接对接任何 OpenAI 兼容 API。

## 对接各框架

### Ollama (最简单)

```bash
ollama pull llama3.2
ollama serve
```

```python
from observer_proxy import ObserverProxy

proxy = ObserverProxy(
    api_url="http://localhost:11434/v1",
    model="llama3.2",
    sensitivity=0.5
)

result = proxy.chat([
    {"role": "user", "content": "朱元璋发明了火锅吗？"}
])

print(result["response"])
print(result["observations"])  # 观察器发现的问题
print(result["status"])         # clean / flagged / interrupted
```

### vLLM (高性能)

```bash
vllm serve meta-llama/Llama-3.2-3B-Instruct
```

```python
proxy = ObserverProxy(
    api_url="http://localhost:8000/v1",
    model="meta-llama/Llama-3.2-3B-Instruct",
    sensitivity=0.5
)
# 用法完全相同
```

### Text Generation Inference (TGI)

```bash
docker run -p 8080:80 ghcr.io/huggingface/text-generation-inference \
    --model-id meta-llama/Llama-3.2-3B-Instruct
```

```python
proxy = ObserverProxy(
    api_url="http://localhost:8080/v1",
    model="meta-llama/Llama-3.2-3B-Instruct",
)
```

### OpenAI API (直接)

```python
proxy = ObserverProxy(
    api_url="https://api.openai.com/v1",
    api_key="sk-...",
    model="gpt-4o-mini",
)
```

### LiteLLM (多模型代理)

LiteLLM 本身就是代理 → ObserverProxy 架在它前面，一个观察器覆盖所有模型。

## 生产化需要的改进

| 当前 | 需要 |
|------|------|
| 单线程阻塞 | 异步 (asyncio + httpx) |
| 规则型观察器 | 接入 1B 小模型做观察器 |
| 离线演示 | 对接实际 API |
| 内存标记 | 持久化审计日志 |
| 固定敏感度 | 每用户/场景可调 |

## 最小可行产品路径

1. 克隆 observer_proxy.py
2. 启动本地 Ollama
3. 对接测试
4. 包装成 HTTP 服务 (FastAPI):
   ```
   POST /v1/chat/completions  ← 用户
      ↓
   ObserverProxy.chat()
      ↓
   Ollama /v1/chat/completions
      ↓
   返回带觉察标记的响应
   ```

5. 这个 HTTP 服务就是「觉察推理网关」——用户和 LLM 之间的透明安全层。

工作量：1-2 周，单人。
