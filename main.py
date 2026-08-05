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

# Подключение к Google Таблицам
if "GOOGLE_CREDENTIALS" in os.environ:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    gc = gspread.service_account_from_dict(creds_dict)
else:
    gc = gspread.service_account(filename="driver-bot-personal-d10024426fab.json")

sh = gc.open("tasks_db")
tasks_sheet = sh.worksheet("Tasks")
analytics_sheet = sh.worksheet("Analytics/Logs" if "Analytics/Logs" in [w.title for w in sh.worksheets()] else "Analytics")

try:
    categories_sheet = sh.worksheet("Categories")
except Exception:
    categories_sheet = None


# ==================== ГЛАВНЫЙ ЭКРАН — ДАШБОРД ====================
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    tasks = tasks_sheet.get_all_records()
    
    total_in_progress = sum(1 for t in tasks if str(t.get('Status', '')).strip() == 'in_progress')
    total_new = sum(1 for t in tasks if str(t.get('Status', '')).strip() == 'new')

    category_names = []
    if categories_sheet:
        cat_records = categories_sheet.get_all_records()
        for row in cat_records:
            cat_val = row.get('Name') or row.get('Project') or list(row.values())[0]
            if cat_val:
                category_names.append(str(cat_val).strip())
    
    for task in tasks:
        cat = str(task.get('Category', '')).strip()
        if cat and cat not in category_names:
            category_names.append(cat)

    if not category_names:
        category_names = ["Amazon", "OKH"]

    grouped_tasks = {cat: [] for cat in category_names}
    other_tasks = []

    for task in tasks:
        task_cat = str(task.get('Category', '')).strip()
        matched = False
        for cat in category_names:
            if cat.lower() == task_cat.lower() or cat.lower() in str(task.get('Title', '')).lower():
                grouped_tasks[cat].append(task)
                matched = True
                break
        if not matched:
            other_tasks.append(task)

    def render_task_rows(task_list):
        if not task_list:
            return '<tr><td colspan="5" class="text-muted text-center">Нет задач в этом блоке</td></tr>'
        res = ""
        for task in task_list:
            status = str(task.get('Status', '')).strip()
            status_color = "warning" if status == "new" else "success" if status == "in_progress" else "secondary"
            pay = task.get('Payment', '')
            pay_str = f"<b>{pay} грн</b>" if pay else "—"
            res += f"""
                <tr>
                    <td>#{task.get('id')}</td>
                    <td><b>{task.get('Title')}</b><br><small class="text-muted">{task.get('Description')}</small></td>
                    <td>{pay_str}</td>
                    <td><span class="badge bg-{status_color}">{status}</span></td>
                    <td>{task.get('Assignee') if task.get('Assignee') else '—'}</td>
                </tr>
            """
        return res

    accordions_html = ""
    for idx, cat in enumerate(category_names):
        cat_tasks = grouped_tasks[cat]
        collapse_id = f"collapse_{idx}"
        show_class = "show" if idx == 0 else ""
        accordions_html += f"""
            <div class="card shadow-sm mb-3">
                <div class="card-header bg-dark text-white d-flex justify-content-between align-items-center" style="cursor: pointer;" data-bs-toggle="collapse" data-bs-target="#{collapse_id}">
                    <h5 class="mb-0">📁 {cat} ({len(cat_tasks)})</h5>
                    <span>▼ Развернуть</span>
                </div>
                <div id="{collapse_id}" class="collapse {show_class}">
                    <div class="card-body">
                        <table class="table table-hover align-middle mb-0">
                            <thead>
                                <tr><th>ID</th><th>Задача</th><th>Оплата</th><th>Статус</th><th>Исполнитель</th></tr>
                            </thead>
                            <tbody>
                                {render_task_rows(cat_tasks)}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        """

    if other_tasks:
        accordions_html += f"""
            <div class="card shadow-sm mb-3">
                <div class="card-header bg-secondary text-white d-flex justify-content-between align-items-center" style="cursor: pointer;" data-bs-toggle="collapse" data-bs-target="#collapse_other">
                    <h5 class="mb-0">📌 Другие задачи ({len(other_tasks)})</h5>
                    <span>▼ Развернуть</span>
                </div>
                <div id="collapse_other" class="collapse">
                    <div class="card-body">
                        <table class="table table-hover align-middle mb-0">
                            <thead>
                                <tr><th>ID</th><th>Задача</th><th>Оплата</th><th>Статус</th><th>Исполнитель</th></tr>
                            </thead>
                            <tbody>
                                {render_task_rows(other_tasks)}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        """

    dashboard_html = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Дашборд — Биржа задач</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
        <div class="container mt-4" style="max-width: 950px;">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2>📊 Дашборд управления задачами</h2>
                <a href="/create" class="btn btn-primary">➕ Выставить задачу</a>
            </div>
            
            <div class="row text-center mb-4">
                <div class="col-md-6">
                    <div class="card shadow-sm p-3 bg-white">
                        <h5 class="text-muted">Новых задач</h5>
                        <h3 class="text-warning">{total_new}</h3>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card shadow-sm p-3 bg-white">
                        <h5 class="text-muted">Всего в работе</h5>
                        <h3 class="text-success">{total_in_progress}</h3>
                    </div>
                </div>
            </div>

            {accordions_html}
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """
    return HTMLResponse(content=dashboard_html)


# ==================== СТРАНИЦА СОЗДАНИЯ ЗАДАЧИ ====================
@app.get("/create", response_class=HTMLResponse)
async def create_page(request: Request):
    category_options = ""
    if categories_sheet:
        for row in categories_sheet.get_all_records():
            cat_val = row.get('Name') or row.get('Project') or list(row.values())[0]
            if cat_val:
                category_options += f'<option value="{cat_val}">{cat_val}</option>'

    create_html = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Выставить задачу</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
        <div class="container mt-5" style="max-width: 600px;">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2>✍️ Создать новое задание</h2>
                <a href="/" class="btn btn-secondary">← Назад на Дашборд</a>
            </div>
            
            <form action="/create-task" method="post" class="card p-4 shadow-sm bg-white">
                <div class="mb-3">
                    <label class="form-label">Выберите проект из списка (или введите ниже):</label>
                    <select name="category_select" class="form-select mb-2" onchange="document.getElementById('customCategory').value=this.value;">
                        <option value="">-- Выберите существующий проект --</option>
                        {category_options}
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Название проекта:</label>
                    <input type="text" name="category" id="customCategory" class="form-control" placeholder="Например: MEXC, Amazon, Розетка" required>
                </div>
                <div class="mb-3">
                    <label class="form-label">Сумма оплаты (грн):</label>
                    <input type="text" name="payment" class="form-control" placeholder="Например: 500 или 555" required>
                </div>
                <div class="mb-3">
                    <label class="form-label">Заголовок задачи:</label>
                    <input type="text" name="title" class="form-control" placeholder="Например: Нужно 6 человек, фото, видео" required>
                </div>
                <div class="mb-3">
                    <label class="form-label">Описание задачи:</label>
                    <textarea name="description" class="form-control" rows="3" required></textarea>
                </div>
                <button type="submit" class="btn btn-primary w-100">Опубликовать в Telegram</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=create_html)


@app.post("/create-task")
async def create_task(category: str = Form(...), payment: str = Form(...), title: str = Form(...), description: str = Form(...)):
    bot = Bot(token=TOKEN)
    
    all_rows = tasks_sheet.get_all_values()
    task_id = len(all_rows) if len(all_rows) > 0 else 1
    
    clean_category = category.strip()
    clean_title = title.strip()
    
    # Красивый заголовок без скобок: 🔥 MEXC — Нужно 6 человек...
    msg_header = f"🔥 <b>{clean_category}</b> — {clean_title}"
    msg_payment = f"💰 <b>Оплата: {payment.strip()} грн</b> 💵🪙"
    
    message_text = f"{msg_header}\n\n{description}\n\n{msg_payment}"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять в работу", callback_data=f"take_{task_id}")]
        ]
    )

    message = await bot.send_message(
        chat_id=GROUP_ID,
        text=message_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    # Сохраняем в таблицу: ID, Title, Description, Status, Assignee, Message_ID, Category, Payment
    tasks_sheet.append_row([task_id, clean_title, description, "new", "", message.message_id, clean_category, payment.strip()])
    await bot.session.close()
    
    return HTMLResponse(content="""
        <div style="text-align:center; margin-top:50px; font-family:sans-serif;">
            <h3>✅ Задача успешно создана и опубликована в группе!</h3>
            <a href="/">На главную (Дашборд)</a> | <a href="/create">Создать еще</a>
        </div>
    """)


# ==================== ЛОГИКА ТЕЛЕГРАМ БОТА ====================
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
            if int(row.get("id", 0)) == task_id:
                target_row_index = idx
                task_data = row
                break

        if not task_data:
            await callback.answer(text="❌ Задача не найдена!", show_alert=True)
            return

        current_assignees = str(task_data.get("Assignee", ""))
        if current_assignees:
            if user_name not in current_assignees.split(", "):
                new_assignees = current_assignees + f", {user_name}"
            else:
                new_assignees = current_assignees
        else:
            new_assignees = user_name

        tasks_sheet.update_cell(target_row_index, 4, "in_progress")
        tasks_sheet.update_cell(target_row_index, 5, new_assignees)

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        analytics_sheet.append_row([current_time, task_id, user_name, user_id, "accepted_task"])

        await callback.answer(text=f"✅ {user_name}, вы добавлены к исполнению!", show_alert=True)
        
        # Обновляем текст в Telegram, сохраняя красивый вид с оплатой и списком исполнителей
        original_text = callback.message.html_text
        if "\n\n🚀" in original_text:
            base_text = original_text.split("\n\n🚀")[0]
        else:
            base_text = original_text
            
        new_text = base_text + f"\n\n🚀 <b>В работе у:</b> {new_assignees}"
        
        try:
            await callback.message.edit_text(text=new_text, reply_markup=callback.message.reply_markup, parse_mode="HTML")
        except Exception:
            pass

    await dp.start_polling(bot)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(start_telegram_bot())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
