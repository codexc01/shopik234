#!/bin/bash
# запуск сервера и бота

cd "$(dirname "$0")"

# подгрузка переменных из .env
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

export BOT_TOKEN="${BOT_TOKEN:-YOUR_BOT_TOKEN}"
export ADMIN_IDS="${ADMIN_IDS:-YOUR_ADMIN_ID}"
export WEBAPP_URL="${WEBAPP_URL:-http://localhost:8000}"

python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
