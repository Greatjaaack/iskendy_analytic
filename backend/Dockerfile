# Официальный образ Playwright с предустановленными браузерами и системными зависимостями.
# Версия должна совпадать с playwright из requirements.txt (1.47.0).
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
