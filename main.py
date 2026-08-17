import asyncio
import logging
import os
import json
import random
from datetime import datetime
from contextlib import asynccontextmanager
import gspread
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
from aiogram import Bot, Dispatcher, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message

TOKEN = "8835314909:AAHItD_URF58cxnr4BlFx3FXakWh6D5ZfGs"
GROUP_ID = -1004303893010

# ==================== ЛОГИКА ТЕЛЕГРАМ БОТА ====================
async def start_telegram_bot():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()

    @dp.callback_query(F.data == "join_promo")
    async def join_promo(callback: CallbackQuery):
        user_id = str(callback.from_user.id)
        user_name = callback.from_user.first_name
        username = callback.from_user.username or ""
        
        if not promo_sheet:
            await callback.answer("❌ Ошибка: лист Promo не найден", show_alert=True)
            return

        rows = promo_sheet.get_all_records()
        existing = next((r for r in rows if str(r.get("Telegram_ID")) == user_id), None)
        
        if existing:
            ticket = existing.get("Ticket")
            await callback.answer(f"Ви вже в акції! Ваш номер: {ticket}", show_alert=True)
            try:
                await callback.message.answer(f"❌ Ви вже в акції! Ваш номер: <b>{ticket}</b>", parse_mode="HTML")
            except:
                pass
        else:
            ticket = random.randint(1000, 9999)
            now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            promo_sheet.append_row([now_time, user_id, user_name, username, ticket])
            
            if drops_sheet:
                drops_rows = drops_sheet.get_all_values()
                user_in_drops = any(len(r) >= 3 and str(r[2]) == user_id for r in drops_rows)
                if not user_in_drops:
                    drops_sheet.append_row([user_name, "", user_id, username, "Средний"])

            try:
                await callback.message.answer(f"🎉 <b>Вітаю, ви прийняли участь у АКЦІЇ!</b>\nВаш номер: <b>{ticket}</b>", parse_mode="HTML")
            except:
                pass
            await callback.answer(f"✅ Готово! Ваш номер: {ticket}", show_alert=True)

    @dp.callback_query(F.data.startswith("take_"))
    async def handle_take_task(callback: CallbackQuery):
        task_id = int(callback.data.split("_")[1])
        user_name = callback.from_user.first_name
        user_id = str(callback.from_user.id)
        user_username = callback.from_user.username or ""

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

        project_name = str(task_data.get("Category", "General")).strip()

        if drops_sheet:
            drops_rows = drops_sheet.get_all_values()
            user_row_idx = None
            
            for idx, row in enumerate(drops_rows, start=1):
                if len(row) >= 3 and str(row[2]) == user_id:
                    user_row_idx = idx
                    break

            if user_row_idx:
                row_data = drops_rows[user_row_idx - 1]
                if user_username and (len(row_data) < 4 or row_data[3] != user_username):
                    drops_sheet.update_cell(user_row_idx, 4, user_username)
                
                user_projects = row_data[5:] if len(row_data) > 5 else []
                if project_name not in user_projects:
                    next_col = max(6, len(row_data) + 1)
                    drops_sheet.update_cell(user_row_idx, next_col, project_name)
            else:
                drops_sheet.append_row([user_name, "", user_id, user_username, "Средний", project_name])

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
        if analytics_sheet:
            analytics_sheet.append_row([current_time, task_id, user_name, user_id, "accepted_task"])

        await callback.answer(text=f"✅ {user_name}, вы добавлены к исполнению!", show_alert=True)
        
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(start_telegram_bot())
    yield

app = FastAPI(lifespan=lifespan)

if "GOOGLE_CREDENTIALS" in os.environ:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    gc = gspread.service_account_from_dict(creds_dict)
else:
    gc = gspread.service_account(filename="driver-bot-personal-d10024426fab.json")

sh = gc.open("tasks_db")
tasks_sheet = sh.worksheet("Tasks")

try:
    analytics_sheet = sh.worksheet("Analytics/Logs" if "Analytics/Logs" in [w.title for w in sh.worksheets()] else "Analytics")
except Exception:
    analytics_sheet = None

try:
    categories_sheet = sh.worksheet("Categories")
except Exception:
    categories_sheet = None

try:
    drops_sheet = sh.worksheet("Drops")
except Exception:
    drops_sheet = None

try:
    promo_sheet = sh.worksheet("Promo")
except Exception:
    promo_sheet = None


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    tasks = tasks_sheet.get_all_records()
    
    total_in_progress = sum(1 for t in tasks if str(t.get('Status', '')).strip() == 'in_progress')
    total_new = sum(1 for t in tasks if str(t.get('Status', '')).strip() == 'new')

    drop_map = {}
    if drops_sheet:
        try:
            drops_rows = drops_sheet.get_all_values()
            for row in drops_rows[1:]:
                if len(row) >= 3:
                    name = str(row[0]).strip()
                    tg_id = str(row[2]).strip()
                    username = str(row[3]).strip() if len(row) > 3 else ""
                    if name and tg_id:
                        drop_map[name] = {"id": tg_id, "username": username}
        except Exception:
            pass

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
        category_names = ["Общие"]

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
            return '<tr><td colspan="7" class="text-muted text-center">Нет задач в этом блоке</td></tr>'
        res = ""
        for task in task_list:
            status = str(task.get('Status', '')).strip()
            task_id = task.get('id')
            
            if status == "new":
                status_color = "warning"
                status_text = "Новая"
                action_btn = ""
                row_class = ""
            elif status == "in_progress":
                status_color = "primary"
                status_text = "В работе"
                action_btn = f'<a href="/close-task/{task_id}" class="btn btn-sm btn-outline-success fw-bold">✅ Завершить</a>'
                row_class = ""
            elif status == "done":
                status_color = "secondary"
                status_text = "Завершена"
                action_btn = "🔒 Закрыта"
                row_class = "table-secondary text-muted"
            else:
                status_color = "secondary"
                status_text = status
                action_btn = ""
                row_class = ""

            pay = task.get('Payment', '')
            pay_str = f"<b>{pay} грн</b>" if pay else "—"
            
            assignee_raw = str(task.get('Assignee', '')).strip()
            names_html = []
            links_html = []
            if assignee_raw:
                for name in assignee_raw.split(', '):
                    names_html.append(f"👤 {name}")
                    if name in drop_map:
                        u_info = drop_map[name]
                        if u_info["username"]:
                            chat_link = f'https://t.me/{u_info["username"]}'
                        else:
                            chat_link = f'tg://user?id={u_info["id"]}'
                        links_html.append(f'<a href="{chat_link}" target="_blank" class="btn btn-sm btn-success py-0 px-2" title="Написать">💬 ТГ</a>')
                    else:
                        links_html.append('<span class="text-muted small">—</span>')
                assignee_display = "<br>".join(names_html)
                links_display = "<br>".join(links_html)
            else:
                assignee_display = "—"
                links_display = "—"
            
            res += f"""
                <tr class="{row_class}">
                    <td>#{task_id}</td>
                    <td><b>{task.get('Title')}</b><br><small class="text-muted">{task.get('Description')}</small></td>
                    <td>{pay_str}</td>
                    <td><span class="badge bg-{status_color}">{status_text}</span></td>
                    <td>{assignee_display}</td>
                    <td>{links_display}</td>
                    <td>{action_btn}</td>
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
                    <div class="card-body p-0">
                        <table class="table table-hover align-middle mb-0">
                            <thead class="table-light">
                                <tr><th>ID</th><th>Задача</th><th>Оплата</th><th>Статус</th><th>Исполнитель</th><th>Связь</th><th>Действие</th></tr>
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
                    <div class="card-body p-0">
                        <table class="table table-hover align-middle mb-0">
                            <thead class="table-light">
                                <tr><th>ID</th><th>Задача</th><th>Оплата</th><th>Статус</th><th>Исполнитель</th><th>Связь</th><th>Действие</th></tr>
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
                <h2>📊 CRM: Управление задачами</h2>
                <div>
                    <a href="/drops" class="btn btn-outline-dark me-2">👥 Дропы</a>
                    <a href="/promo-setup" class="btn btn-warning me-2">🎰 Добавить акцию</a>
                    <a href="/create" class="btn btn-primary">➕ Выставить задачу</a>
                </div>
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
@app.get("/close-task/{task_id}")
async def close_task(task_id: int):
    rows = tasks_sheet.get_all_records()
    for idx, row in enumerate(rows, start=2):
        if str(row.get("id")) == str(task_id):
            tasks_sheet.update_cell(idx, 4, "done")
            break
    return RedirectResponse(url="/", status_code=303)


@app.post("/update-phone")
async def update_phone(tg_id: str = Form(...), phone: str = Form(...)):
    if drops_sheet:
        try:
            drops_rows = drops_sheet.get_all_values()
            for idx, row in enumerate(drops_rows, start=1):
                if len(row) >= 3 and str(row[2]) == tg_id:
                    drops_sheet.update_cell(idx, 2, phone)
                    break
        except Exception:
            pass
    return RedirectResponse(url="/drops", status_code=303)


@app.post("/update-adequacy")
async def update_adequacy(tg_id: str = Form(...), status: str = Form(...)):
    if drops_sheet:
        try:
            drops_rows = drops_sheet.get_all_values()
            for idx, row in enumerate(drops_rows, start=1):
                if len(row) >= 3 and str(row[2]) == tg_id:
                    drops_sheet.update_cell(idx, 5, status)
                    break
        except Exception:
            pass
    return RedirectResponse(url="/drops", status_code=303)


@app.get("/promo-setup", response_class=HTMLResponse)
async def promo_setup(request: Request):
    promo_rows = promo_sheet.get_all_values()[1:] if promo_sheet else []
    
    rows_html = ""
    for r in promo_rows:
        date_reg = r[0] if len(r) > 0 else ""
        name = r[2] if len(r) > 2 else "Без имени"
        uname = r[3] if len(r) > 3 else ""
        ticket = r[4] if len(r) > 4 else ""
        
        if uname:
            chat_link = f'<a href="https://t.me/{uname}" target="_blank">@{uname}</a>'
        else:
            chat_link = "—"

        rows_html += f"<tr><td>{date_reg}</td><td><b>{name}</b><br><small>{chat_link}</small></td><td><span class='badge bg-success fs-6'>{ticket}</span></td></tr>"

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Запустить акцию</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
        <div class="container mt-5" style="max-width: 800px;">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2>🎰 Управление акцией и статистика</h2>
                <a href="/" class="btn btn-secondary">← Назад на Дашборд</a>
            </div>
            
            <form action="/send-promo" method="post" class="card p-4 shadow-sm bg-white mb-4">
                <div class="mb-3">
                    <label class="form-label text-muted fw-bold">Текст акции для публикации в группе:</label>
                    <textarea name="text" class="form-control" rows="3" placeholder="Например: 🎁 Розыгрыш! Нажмите кнопку ниже..." required></textarea>
                </div>
                <button type="submit" class="btn btn-warning btn-lg w-100 fw-bold">🚀 Опубликовать акцию в Telegram</button>
            </form>

            <div class="card shadow-sm bg-white p-3">
                <h4 class="mb-3">📋 Список участников ({len(promo_rows)})</h4>
                <table class="table table-hover align-middle">
                    <thead class="table-dark">
                        <tr><th>Дата</th><th>Участник</th><th>Счастливый билет</th></tr>
                    </thead>
                    <tbody>
                        {rows_html if rows_html else '<tr><td colspan="3" class="text-center text-muted">Пока никто не зарегистрировался</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """)


@app.post("/send-promo")
async def send_promo(text: str = Form(...)):
    bot = Bot(token=TOKEN)
    try:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎰 Участвовать в акции", callback_data="join_promo")]
            ]
        )
        await bot.send_message(chat_id=GROUP_ID, text=text, reply_markup=keyboard)
        print("✅ Акция успешно отправлена в группу!")
    except Exception as e:
        print(f"❌ ОШИБКА ОТПРАВКИ В ТЕЛЕГРАМ: {e}")
    finally:
        await bot.session.close()
        
    return RedirectResponse(url="/", status_code=303)


@app.get("/drops", response_class=HTMLResponse)
async def drops_page(request: Request):
    rows_html = ""
    
    if drops_sheet:
        try:
            drops_rows = drops_sheet.get_all_values()
            for row in drops_rows[1:]:
                u_name = row[0] if len(row) > 0 else "Без имени"
                u_phone = row[1] if len(row) > 1 else ""
                u_id = row[2] if len(row) > 2 else ""
                u_username = row[3] if len(row) > 3 else ""
                adequacy = row[4] if len(row) > 4 else "Средний"
                
                projects = row[5:] if len(row) > 5 else []
                projects = [p for p in projects if p.strip()] 
                
                badges = " ".join([f'<span class="badge bg-info text-dark">{p}</span>' for p in projects])
                if not badges:
                    badges = '<span class="text-muted small">Нет проектов</span>'
                
                if u_username:
                    tg_link = f'<a href="https://t.me/{u_username}" target="_blank" class="btn btn-sm btn-success fw-bold">💬 Написать в ТГ</a>'
                elif u_id:
                    tg_link = f'<a href="tg://user?id={u_id}" target="_blank" class="btn btn-sm btn-success fw-bold">💬 Написать в ТГ</a>'
                else:
                    tg_link = '—'
                
                if adequacy == "Адекватный":
                    row_bg = "table-success"
                elif adequacy == "Неадекватный":
                    row_bg = "table-danger"
                else:
                    row_bg = "table-warning"
                
                if u_name or u_id:
                    rows_html += f"""
                        <tr class="{row_bg}">
                            <td><b>{u_name}</b><br><small class="text-muted">@{u_username} (ID: {u_id})</small></td>
                            <td>
                                <form action="/update-phone" method="post" class="d-flex" style="max-width: 220px;">
                                    <input type="hidden" name="tg_id" value="{u_id}">
                                    <input type="text" name="phone" class="form-control form-control-sm me-1" value="{u_phone}" placeholder="+380...">
                                    <button type="submit" class="btn btn-sm btn-outline-secondary" title="Сохранить">💾</button>
                                </form>
                            </td>
                            <td>
                                <form action="/update-adequacy" method="post">
                                    <input type="hidden" name="tg_id" value="{u_id}">
                                    <select name="status" class="form-select form-select-sm" onchange="this.form.submit()" style="width: 140px;">
                                        <option value="Адекватный" {'selected' if adequacy == 'Адекватный' else ''}>Адекватный</option>
                                        <option value="Средний" {'selected' if adequacy == 'Средний' else ''}>Средний</option>
                                        <option value="Неадекватный" {'selected' if adequacy == 'Неадекватный' else ''}>Неадекватный</option>
                                    </select>
                                </form>
                            </td>
                            <td>{badges}</td>
                            <td>{tg_link}</td>
                        </tr>
                    """
        except Exception:
            pass

    if not rows_html:
        rows_html = '<tr><td colspan="5" class="text-center text-muted p-4">База пока пуста. Люди появятся здесь автоматически!</td></tr>'

    drops_html = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Список Дропов</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
        <div class="container mt-4" style="max-width: 1100px;">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2>👥 CRM: База исполнителей</h2>
                <a href="/" class="btn btn-secondary">← Назад на Дашборд</a>
            </div>
            
            <div class="card shadow-sm bg-white p-3">
                <table class="table table-hover align-middle mb-0">
                    <thead class="table-dark">
                        <tr>
                            <th>Имя / Ник</th>
                            <th>Телефон</th>
                            <th>Адекватность</th>
                            <th>Выполненные проектов</th>
                            <th>Связь</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=drops_html)


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
                    <label class="form-label text-muted fw-bold">Выберите проект из списка (или введите ниже):</label>
                    <select name="category_select" class="form-select mb-2" onchange="document.getElementById('customCategory').value=this.value;">
                        <option value="">-- Выберите существующий проект --</option>
                        {category_options}
                    </select>
                </div>
                <div class="mb-3">
                    <input type="text" name="category" id="customCategory" class="form-control form-control-lg" placeholder="Например: MEXC, Amazon, Розетка" required>
                </div>
                <div class="mb-3">
                    <label class="form-label text-muted fw-bold">Сумма оплаты (грн):</label>
                    <input type="text" name="payment" class="form-control form-control-lg" placeholder="Например: 500 или 555" required>
                </div>
                <div class="mb-3">
                    <label class="form-label text-muted fw-bold">Описание задачи:</label>
                    <textarea name="description" class="form-control" rows="4" placeholder="Например: Нужно 6 человек, сделать фото и видео верификации" required></textarea>
                </div>
                <button type="submit" class="btn btn-primary btn-lg w-100">Опубликовать в Telegram</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=create_html)


@app.post("/create-task")
async def create_task(category: str = Form(...), payment: str = Form(...), description: str = Form(...)):
    bot = Bot(token=TOKEN)
    
    all_rows = tasks_sheet.get_all_values()
    task_id = len(all_rows) if len(all_rows) > 0 else 1
    
    clean_category = category.strip()
    msg_header = f"🔥 <b>{clean_category}</b>"
    msg_payment = f"💰💰 <b>Оплата: {payment.strip()} грн</b> 💰💰"
    
    message_text = f"{msg_header}\n\n{description.strip()}\n\n{msg_payment}"
    
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
    
    tasks_sheet.append_row([task_id, clean_category, description.strip(), "new", "", message.message_id, clean_category, payment.strip()])
    await bot.session.close()
    
    return HTMLResponse(content="""
        <div style="text-align:center; margin-top:50px; font-family:sans-serif;">
            <h3 style="color: #198754;">✅ Задача успешно создана и опубликована в группе!</h3>
            <br><br>
            <a href="/" style="padding: 10px 20px; background: #0d6efd; color: white; text-decoration: none; border-radius: 5px;">На главную (Дашборд)</a> 
            &nbsp;&nbsp;
            <a href="/create" style="padding: 10px 20px; background: #6c757d; color: white; text-decoration: none; border-radius: 5px;">Создать еще</a>
        </div>
    """)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
