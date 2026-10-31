FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md DECISIONS.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV MEDIA_DOWNLOADS_ROOT=/downloads MEDIA_AUDIT_PATH=/config/audit.jsonl MEDIA_DRY_RUN=true
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=15s CMD python -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3); assert r.status == 200 and json.load(r).get('ok') is True"
ENTRYPOINT ["media-stack"]
CMD ["serve"]
