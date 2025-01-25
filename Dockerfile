# 기본 이미지 설정
FROM python:3.10-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    # 기본 빌드 도구
    build-essential \
    pkg-config \
    python3-dev \
    # MySQL 관련
    default-libmysqlclient-dev \
    # Java 관련 (konlpy용)
    default-jdk \
    # 크롤링 관련
    wget \
    gnupg \
    unzip \
    chromium \
    chromium-driver \
    # 시스템 라이브러리
    libglib2.0-0 \
    libnss3 \
    libgconf-2-4 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# 기본 Python 패키지 설치 (의존성이 적은 것부터)
COPY requirements.txt .
RUN pip install --no-cache-dir \
    wheel \
    setuptools \
    && pip install --no-cache-dir -r requirements.txt

# 프로젝트 파일 복사
COPY . .

# 크롬드라이버 권한 설정
RUN chmod +x /usr/bin/chromedriver

# 환경변수 설정
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=newsdocs.settings
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# 포트 설정
EXPOSE 8000

# 실행 명령
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "config.wsgi:application"] 