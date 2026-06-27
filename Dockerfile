# 生产镜像 — 零外部依赖，镜像 < 100MB
FROM python:3.13-alpine

LABEL org.opencontainers.image.title="Anchor Gateway"
LABEL org.opencontainers.image.description="Zero-dependency LLM hallucination detection middleware with billing & dashboard"
LABEL org.opencontainers.image.version="3.0.0"
LABEL com.awareness.security.review="2026-06-02"
LABEL com.awareness.security.level="production"
LABEL org.opencontainers.image.authors="Li Qiao"
LABEL org.opencontainers.image.url="https://github.com/malaxiya20250530-glitch/shiyan2925"

RUN adduser -D -h /app gateway
WORKDIR /app

# 核心模块
COPY hallucination_detector.py .
COPY checker_classes.py .
COPY checker_registry.py .
COPY awareness_gateway.py .
COPY knowledge_graph.py .
COPY vector_kb.py .
COPY consensus_engine.py .
COPY ml_consensus.py .
COPY observer_security.py .
COPY observer_proxy.py .
COPY alignment_middleware.py .

# 计费 + 仪表盘
COPY billing.py .
COPY dashboard_server.py .
COPY rate_limiter.py .

# 知识库
COPY kb_core.json .
COPY kb_medical.json .
COPY kb_legal.json .
COPY kb_loader.py .

# 可选模块
COPY web_verifier.py .
COPY feedback_store.py .
COPY feedback_collector.py .
COPY auto_kb_updater.py .
COPY logger.py .
COPY security_logger.py .

# 配置文件
COPY config.json .

RUN chown -R gateway:gateway /app
USER gateway

EXPOSE 8800 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8800/health')"

# 安全加固: 只读文件系统 + 能力限制 (需要运行时 --read-only --cap-drop=ALL)
# 运行: docker run --read-only --cap-drop=ALL --tmpfs /tmp \
#        -v feedback.db:/app/feedback.db:rw anchor-gateway
ENTRYPOINT ["python3", "awareness_gateway.py"]
CMD ["--mock", "--port", "8800"]
