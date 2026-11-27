FROM python:3.12.16-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
WORKDIR /opt/xephyguard/analysis
COPY analysis/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY analysis/xg_analysis ./xg_analysis
COPY data/analysis /opt/xephyguard/data/analysis
ENV XG_ANALYSIS_PORT=8090 XG_DATA_DIR=/opt/xephyguard/data
USER nobody
CMD ["python", "-m", "xg_analysis", "serve"]
