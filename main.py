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
analytics_sheet = sh.worksheet("Analytics")

# ==================== ГЛАВНЫЙ ЭКРАН — ДАШБОРД ====================
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    tasks = tasks_sheet.get_all_records()
    
    # Считаем общую статистику
    total_in_progress = sum(1 for t in tasks if t.get('Status') == 'in_progress')
    total_new = sum(1 for t in tasks if t.get('Status') == 'new')

    # Группируем задачи по категориям (например, по префиксу или названию, или выделим Amazon / OKH)
    # Предположим, что в заголовке или отдельном поле указан проект. Для примера разделим по ключевым словам.
    amazon_tasks = [t for t in tasks if "amazon" in str(t.get('Title', '')).lower() or "амазон" in str(t.get('Title', '')).lower()]
    okh_tasks = [t for t in tasks if "okh" in str(t.get('Title', '')).lower() or "окх" in str(t.get('Title', '')).lower()]
    other_tasks = [t for t in tasks if t not in amazon_tasks and t not in okh_tasks]

    def render_task_rows(task_list):
        if not task_list:
            return '<tr><td colspan="4" class="text-muted text-center">Нет задач в этом блоке</td></tr>'
        res = ""
        for task in task_list:
            status_color = "warning" if task.get('Status') == "new" else "success" if task.get('Status') == "in_progress" else "secondary"
            res += f"""
                <tr>
                    <td>#{task.get('id')}</td>
                    <td><b>{task.get('Title')}</b><br><small class="text-muted">{task.get('Description')}</small></td>
                    <td><span class="badge bg-{status_color}">{task.get('Status')}</span></td>
                    <td>{task.get('Assignee') if task.get('Assignee') else '—'}</td>
                </tr>
            """
        return res

    dashboard_html = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Дашборд — Биржа задач</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
        <div class="container mt-4" style="max-width: 900px;">
            <!-- Шапка с переключателем -->
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2>📊 Дашборд управления задачами</h2>
                <a href="/create" class="btn btn-primary">➕ Выставить задачу</a>
            </div>
            
            <!-- Блок общей инфы сверху -->
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

            <!-- БЛОК: AMAZON (Аккордеон) -->
            <div class="card shadow-sm mb-3">
                <div class="card-header bg-dark text-white d-flex justify-content-between align-items-center" style="cursor: pointer;" data-bs-toggle="collapse" data-bs-target="#amazonCollapse">
                    <h5 class="mb-0">📦 Запрос Amazon ({len(amazon_tasks)})</h5>
                    <span>▼ Развернуть</span>
                </div>
                <div id="amazonCollapse" class="collapse show">
                    <div class="card-body">
                        <table class="table table-hover align-middle mb-0">
                            <thead>
                                <tr><th>ID</th><th>Задача</th><th>Статус</th><th>Исполнитель</th></tr>
                            </thead>
                            <tbody>
                                {render_task_rows(amazon_tasks)}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- БЛОК: OKH (Аккордеон) -->
            <div class="card shadow-sm mb-3">
                <div class="card-header bg-dark text-white d-flex justify-content-between align-items-center" style="cursor: pointer;" data-bs-toggle="collapse" data-bs-target="#okhCollapse">
                    <h5 class="mb-0">🏢 Запрос OKH ({len(okh_tasks)})</h5>
                    <span>▼ Развернуть</span>
                </div>
                <div id="okhCollapse" class="collapse">
                    <div class="card-body">
                        <table class="table table-hover align-middle mb-0">
                            <thead>
                                <tr><th>ID</th><th>Задача</th><th>Статус</th><th>Исполнитель</th></tr>
                            </thead>
                            <tbody>
                                {render_task_rows(okh_tasks)}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- БЛОК: Остальные / Общие задачи (Аккордеон) -->
            <div class="card shadow-sm mb-3">
                <div class="card-header bg-secondary text-white d-flex justify-content-between align-items-center" style="cursor: pointer;" data-bs-toggle="collapse" data-bs-target="#otherCollapse">
                    <h5 class="mb-0">📌 Общие / Другие задачи ({len(other_tasks)})</h5>
                    <span>▼ Развернуть</span>
                </div>
                <div id="otherCollapse" class="collapse">
                    <div class="card-body">
                        <table class="table table-hover align-middle mb-0">
                            <thead>
                                <tr><th>ID</th><th>Задача</th><th>Статус</th><th>Исполнитель</th></tr>
                            </thead>
                            <tbody>
                                {render_task_rows(other_tasks)}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """
    return HTMLResponse(content=dashboard_html)


# ==================== СТРАНИЦА СОЗДАНИЯ ЗАДАЧИ ====================
@app.get("/create", response_class=HTMLResponse)
async def create_page(request: Request):
    create_html = """
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
                    <label class="form-label">Шаблон постоянной задачи:</label>
                    <select class="form-select mb-2" id="templateSelect" onchange="fillTemplate()">
                        <option value="">-- Выберите шаблон (опционально) --</option>
                        <option value="Amazon: Проверка листинга|Проверить актуальные цены и остатки на Amazon по списку SKU.">Amazon: Проверка листинга</option>
                        <option value="OKH: Сверка отчетов|Выгрузить еженедельный финансовый отчет по системе OKH.">OKH: Сверка отчетов</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Заголовок задачи:</label>
                    <input type="text" name="title" id="taskTitle" class="form-control" required>
                </div>
                <div class="mb-3">
                    <label class="form-label">Описание задачи:</label>
                    <textarea name="description" id="taskDesc" class="form-control" rows="4" required></textarea>
                </div>
                <button type="submit" class="btn btn-primary w-100">Опубликовать в Telegram</button>
            </form>
        </div>

        <script>
            function fillTemplate() {
                let val = document.getElementById("templateSelect").value;
                if (val) {
                    let parts = val.split("|");
                    document.getElementById("taskTitle").value = parts[0];
                    document.getElementById("taskDesc").value = parts[1];
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=create_html)


@app.post("/create-task")
async def create_task(title: str = Form(...), description: str = Form(...)):
    bot = Bot(token=TOKEN)
    
    all_rows = tasks_sheet.get_all_values()
    task_id = len(all_rows) if len(all_rows) > 0 else 1
    
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
    
    tasks_sheet.append_row([task_id, title, description, "new", "", message.message_id])
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
        
        current_text = callback.message.html_text.split("\n\n🚀")[0]
        new_text = current_text + f"\n\n🚀 <b>В работе у:</b> {new_assignees}"
        
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
