FROM python:3.11-slim

# Instalar dependencias del sistema para reportlab (fonts Lato)
RUN apt-get update && apt-get install -y \
    fonts-lato \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY . .

EXPOSE 8080

CMD ["python", "app.py"]
