#!/bin/bash
set -e

echo "=== Iskendy Analytics ==="
echo ""

# Backend
echo "Запускаю backend..."
cd backend
pip install -r requirements.txt -q
python -m playwright install chromium
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd ..

# Frontend
echo "Запускаю frontend..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo ""
echo "Ctrl+C для остановки"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
