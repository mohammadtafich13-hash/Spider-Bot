FROM python:3.10-slim

# تثبيت ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# إعداد مجلد العمل
WORKDIR /app

# نسخ الملفات وتثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# تشغيل البوت
CMD ["python", "bot.py"]
