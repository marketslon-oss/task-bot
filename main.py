import asyncio
import logging
import os
import json
from datetime import datetime
import gspread
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

app = FastAPI()

TOKEN = "8835314909:AAHItD_URF58cxnr4BlFx3FXakWh6D5ZfGs"
GROUP_ID = -1004303893010

# =================================================================
# ИСПРАВЛЕНИЕ 1: Безопасное подключение к Google Таблицам для Render
# =================================================================
if "GOOGLE_CREDENTIALS" in os.environ:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    gc = gspread.service_account_from_dict(creds_dict)
else:
    gc = gspread.service_account(filename="driver-bot-personal-d10024426fab.json")

sh = gc.open("tasks_db")
tasks_sheet = sh.worksheet("Tasks")
analytics_sheet = sh.worksheet("Analytics")

# Главная страница (Форма создания + ссылки на дашборд)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Биржа задач — Панель управления</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container mt-5" style="max-width: 700px;">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2>📢 Биржа задач</h2>
            <a href="/dashboard" class="btn btn-outline-primary">📊 Открыть Дашборд аналитики</a>
        </div>
        
        <form action="/create-task" method="post" class="card p-4 shadow-sm">
            <h4 class="mb-3">Создать новое задание</h4>
            <div class="mb-3">
                <label class="form-label">Заголовок задачи:</label>
                <input type="text" name="title" class="form-control" required>
            </div>
            <div class="mb-3">
                <label class="form-label">Описание задачи:</label>
                <textarea name="description" class="form-control" rows="4" required></textarea>
            </div>
            <button type="submit" class="btn btn-primary w-100">Опубликовать в Telegram</button>
        </form>
    </div>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return HTMLResponse(content=HTML_TEMPLATE)

# Страница Веб-Дашборда аналитики
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    tasks = tasks_sheet.get_all_records()
    
    rows_html = ""
    for task in tasks:
        status_color = "warning" if task['Status'] == "new" else "success" if task['Status'] == "in_progress" else "secondary"
        rows_html += f"""
            <tr>
                <td>{task['id']}</td>
                <td><b>{task['Title']}</b><br><small class="text-muted">{task['Description']}</small></td>
                <td><span class="badge bg-{status_color}">{task['Status']}</span></td>
                <td>{task['Assignee'] if task['Assignee'] else '—'}</td>
            </tr>
        """

    dashboard_html = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Дашборд аналитики задач</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
        <div class="container mt-5">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2>📊 Дашборд аналитики и статусов</h2>
                <a href="/" class="btn btn-secondary">← Назад к созданию задач</a>
            </div>
            
            <div class="card shadow-sm p-3">
                <table class="table table-hover align-middle">
                    <thead class="table-dark">
                        <tr>
                            <th>ID</th>
                            <th>Задача</th>
                            <th>Статус</th>
                            <th>Исполнитель(-и)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html if rows_html else '<tr><td colspan="4" class="text-center">Задач пока нет</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=dashboard_html)

@app.post("/create-task")
async def create_task(title: str = Form(...), description: str = Form(...)):
    bot = Bot(token=TOKEN)
    
    all_rows = tasks_sheet.get_all_values()
    task_id = len(all_rows) if len(all_rows) > 0 else 1
    
    # Кнопка остается активной (НЕ удаляется при клике)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять в работу", callback_data=f"take_{task_id}")]
        ]
    )

    message = await bot.send_message(
        chat_id=GROUP_ID,
        text=f"🔥 <b>{title}</b>\n\n{description}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    # Сохраняем задачу в Google Таблицу (Assignee делаем пустым/накопительным)
    tasks_sheet.append_row([task_id, title, description, "new", "", message.message_id])
    
    await bot.session.close()
    return HTMLResponse(content="""
        <div style="text-align:center; margin-top:50px; font-family:sans-serif;">
            <h3>✅ Задача успешно создана и опубликована в группе!</h3>
            <a href="/">Создать еще одну</a> | <a href="/dashboard">Открыть дашборд</a>
        </div>
    """)

# Логика бота для мульти-кликов (кнопка активна, фиксируем каждого откликнувшегося)
async def start_telegram_bot():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()

    @dp.callback_query(F.data.startswith("take_"))
    async def handle_take_task(callback: CallbackQuery):
        task_id = int(callback.data.split("_")[1])
        user_name = callback.from_user.first_name
        user_id = callback.from_user.id

        rows = tasks_sheet.get_all_records()
        target_row_index = None
        task_data = None
        
        for idx, row in enumerate(rows, start=2):
            if int(row["id"]) == task_id:
                target_row_index = idx
                task_data = row
                break

        if not task_data:
            await callback.answer(text="❌ Задача не найдена!", show_alert=True)
            return

        # Дописываем нового исполнителя через запятую, если задачу уже кто-то брал
        current_assignees = str(task_data["Assignee"])
        if current_assignees:
            if user_name not in current_assignees.split(", "):
                new_assignees = current_assignees + f", {user_name}"
            else:
                new_assignees = current_assignees
        else:
            new_assignees = user_name

        # Обновляем статус на "in_progress" и добавляем исполнителя в таблицу
        tasks_sheet.update_cell(target_row_index, 4, "in_progress")
        tasks_sheet.update_cell(target_row_index, 5, new_assignees)

        # Пишем подробный лог в аналитику
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        analytics_sheet.append_row([current_time, task_id, user_name, user_id, "accepted_task"])

        # Уведомляем пользователя всплывающим окном
        await callback.answer(text=f"✅ {user_name}, вы добавлены к исполнению задачи!", show_alert=True)
        
        # Обновляем текст в сообщении чата, показывая список текущих исполнителей, но КНОПКУ НЕ УДАЛЯЕМ!
        current_text = callback.message.html_text.split("\n\n🚀")[0]  # Берем чистый текст задачи
        new_text = current_text + f"\n\n🚀 <b>В работе у:</b> {new_assignees}"
        
        # Перезаписываем сообщение, оставляя клавиатуру (кнопку) активной
        try:
            await callback.message.edit_text(text=new_text, reply_markup=callback.message.reply_markup, parse_mode="HTML")
        except Exception:
            pass # Игнорируем ошибку, если текст не изменился

    await dp.start_polling(bot)

if __name__ == "__main__":
    import threading
    
    def run_bot():
        asyncio.run(start_telegram_bot())
        
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # =================================================================
    # ИСПРАВЛЕНИЕ 2: Хост 0.0.0.0 и динамический порт для Render
    # =================================================================
  # ==================== АВТОМАТИЧЕСКИЙ СТАРТ БОТА С FASTAPI ====================
@app.on_event("startup")
async def startup_event():
    # Запускаем поллинг бота в фоновом режиме внутри асинхронного цикла FastAPI
    asyncio.create_task(start_telegram_bot())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
