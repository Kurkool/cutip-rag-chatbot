# ใช้ Python 3.11 รุ่น slim เพื่อประสิทธิภาพที่รวดเร็วและ image ขนาดเล็ก
FROM python:3.11-slim

# ตั้งค่า Working Directory ใน Container
WORKDIR /app

# ก๊อปปี้ไฟล์ requirements.txt มาติดตั้งก่อน (เพื่อใช้ประโยชน์จาก Docker Cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ก๊อปปี้โค้ดทั้งหมดในโฟลเดอร์ของเราไปไว้ใน Container
COPY . .

# เปิด Port 8000
EXPOSE 8000

# คำสั่งรัน FastAPI เมื่อ Container เริ่มทำงาน
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
