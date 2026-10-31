FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md DECISIONS.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV MEDIA_DOWNLOADS_ROOT=/downloads MEDIA_AUDIT_PATH=/config/audit.jsonl MEDIA_DRY_RUN=true
EXPOSE 8080
ENTRYPOINT ["media-stack"]
CMD ["serve"]
