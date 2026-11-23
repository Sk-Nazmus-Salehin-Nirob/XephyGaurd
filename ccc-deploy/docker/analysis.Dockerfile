FROM python:3.12-slim
WORKDIR /opt/xephyguard/analysis
COPY analysis/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY analysis/xg_analysis ./xg_analysis
COPY data/analysis /opt/xephyguard/data/analysis
ENV XG_ANALYSIS_PORT=8090 XG_DATA_DIR=/opt/xephyguard/data
USER nobody
CMD ["python", "-m", "xg_analysis", "serve"]
