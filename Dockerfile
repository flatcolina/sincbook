FROM python:3.11-slim
WORKDIR /app
COPY requirements_robos.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV TZ=America/Sao_Paulo
CMD ["python3","robo_ical_booking.py"]
