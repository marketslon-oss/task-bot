import asyncio
import logging
import os
import json
import random
import html
from datetime import datetime
from contextlib import asynccontextmanager

import gspread
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
TOKEN = "8835314909:AAHItD_URF58cxnr4BlFx3FXakWh6D5ZfGs"
GROUP_ID = -1004303893010
BOT_USERNAME = "my_test_verif_bot"

# ==================== ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS ====================
if "GOOGLE_CREDENTIALS" in os.environ:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    gc = gspread.service_account_from_dict(creds_dict)
else:
    gc = gspread.service_account(filename="driver-bot-personal-d10024426fab.json")

sh = gc.open("tasks_db")

def get_sheet(name):
    try:
        return sh.worksheet(name)
    except Exception as e:
        logger.warning(f"Лист '{name}' не найден: {e}")
        return None

tasks_sheet = get_sheet("Tasks")
analytics_sheet = get_sheet("Analytics") or get_sheet("Analytics/Logs")
categories_sheet = get_sheet("Categories")
drops_sheet = get_sheet("Drops")
promo_sheet = get_sheet("Promo")

if promo_sheet is None:
    logger.error("❌ Лист 'Promo' не найден! Создайте его с колонками: Date, Telegram_ID, Name, Username, Ticket")
if drops_sheet is None:
    logger.error("❌ Лист 'Drops' не найден! Создайте его с колонками: Name, Phone, Telegram_ID, Username, Adequacy, Completed_Tasks")

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def get_next_task_id():
    if tasks_sheet is None:
        return 1
    records = tasks_sheet.get_all_records()
    if not records:
        return 1
    ids = [r.get("id", 0) for r in records if isinstance(r.get("id"), (int, float))]
    return max(ids) + 1 if ids else 1

def register_user_with_number(user_id: str, user_name: str, username: str, number: int):
    if promo_sheet is None:
        return None, False

    try:
        all_rows = promo_sheet.get_all_values()
        existing_ticket = None
        for row in all_rows:
            if len(row) >= 2 and str(row[1]) == user_id:
                if len(row) >= 5:
                    existing_ticket = row[4]
                break

        if existing_ticket is not None:
            return existing_ticket, False

        ticket = random.randint(1000, 9999)
        now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        promo_sheet.append_row([now_time, user_id, user_name, username, ticket])

        if drops_sheet is not None:
            drops_rows = drops_sheet.get_all_values()
            exists = False
            for row in drops_rows[1:]:
                if len(row) >= 3 and str(row[2]) == user_id:
                    exists = True
                    break
            if not exists:
                drops_sheet.append_row([user_name, "", user_id, username, "Средний", ""])

        return ticket, True
    except Exception as e:
        logger.error(f"❌ Ошибка в register_user_with_number: {e}")
        return None, False

# ==================== ЛОГИКА ТЕЛЕГРАМ БОТА ====================
async def start_telegram_bot():
    await asyncio.sleep(2)
    
    bot = Bot(token=TOKEN)
    await bot.delete_webhook()
    logger.info("✅ Webhook deleted")
    
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start_command(message: Message):
        args = message.text.split()
        deep_link = args[1] if len(args) > 1 else None

        if deep_link == "promo":
            webapp_url = "https://mayer-pro.onrender.com/roulette"
            # Замена на ReplyKeyboardMarkup
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="🎰 Відкрити рулетку", web_app=WebAppInfo(url=webapp_url))]
                ],
                resize_keyboard=True,
                one_time_keyboard=False
            )
            await message.answer(
                "🎡 Натисніть велику кнопку <b>ВНИЗУ екрана</b>, щоб покрутити колесо і дізнатися свій номер!",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await message.answer("Привіт! Використовуйте кнопку в групі для участі в акції.")

    @dp.message(F.web_app_data)
    async def handle_web_app_data(message: Message):
        try:
            data = json.loads(message.web_app_data.data)
            number = data.get('number')
            if number is None:
                await message.answer("❌ Помилка: не вдалося отримати число.")
                return

            user_id = str(message.from_user.id)
            user_name = message.from_user.first_name
            username = message.from_user.username or ""

            ticket, is_new = register_user_with_number(user_id, user_name, username, number)

            if ticket is None:
                await message.answer("❌ Сталася помилка реєстрації. Спробуйте пізніше.")
                return

            if is_new:
                await message.answer(
                    f"🎉 <b>Вітаю, ви прийняли участь у АКЦІЇ!</b>\n"
                    f"Ваш щасливий номер: <b>{ticket}</b>\n"
                    f"Випало на колесі: <b>{number}</b>",
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                await message.answer(
                    f"❌ Ви вже зареєстровані в акції!\n"
                    f"Ваш номер: <b>{ticket}</b>\n"
                    f"Останнє випало на колесі: <b>{number}</b>",
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove()
                )
        except Exception as e:
            logger.error(f"❌ Ошибка обработки web_app_data: {e}")
            await message.answer("❌ Сталася помилка. Спробуйте ще раз.")

    @dp.callback_query(F.data == "join_promo")
    async def join_promo(callback: CallbackQuery):
        webapp_url = "https://mayer-pro.onrender.com/roulette"
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🎰 Відкрити рулетку", web_app=WebAppInfo(url=webapp_url))]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        await callback.answer("Відкриваємо меню акції...")
        # При ReplyKeyboardMarkup нужно отправлять новое сообщение, а не редактировать старое
        await callback.message.answer(
            "🎡 Натисніть велику кнопку <b>ВНИЗУ екрана</b>, щоб покрутити колесо і дізнатися свій номер!",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("take_"))
    async def handle_take_task(callback: CallbackQuery):
        task_id = int(callback.data.split("_")[1])
        user_name = callback.from_user.first_name
        user_id = str(callback.from_user.id)
        user_username = callback.from_user.username or ""

        if tasks_sheet is None:
            await callback.answer("❌ Лист задач не знайдено!", show_alert=True)
            return

        rows = tasks_sheet.get_all_records()
        target_row_index = None
        task_data = None
        
        for idx, row in enumerate(rows, start=2):
            if int(row.get("id", 0)) == task_id:
                target_row_index = idx
                task_data = row
                break

        if task_data is None:
            await callback.answer(text="❌ Задача не найдена!", show_alert=True)
            return

        project_name = str(task_data.get("Category", "General")).strip()

        if drops_sheet is not None:
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
                
                if len(row_data) >= 6:
                    completed = row_data[5] if row_data[5] else ""
                    projects_list = [p.strip() for p in completed.split(',') if p.strip()]
                    if project_name not in projects_list:
                        projects_list.append(project_name)
                        new_completed = ', '.join(projects_list)
                        drops_sheet.update_cell(user_row_idx, 6, new_completed)
                else:
                    drops_sheet.update_cell(user_row_idx, 6, project_name)
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
        if analytics_sheet is not None:
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
        except Exception as e:
            logger.warning(f"Не удалось обновить сообщение: {e}")

    await dp.start_polling(bot)

# ==================== FASTAPI ВЕБ-СЕРВЕР ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(start_telegram_bot())
    yield

app = FastAPI(lifespan=lifespan)

# ---------- СТРАНИЦА РУЛЕТКИ (WebApp) ----------
@app.get("/roulette", response_class=HTMLResponse)
async def roulette_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🎰 Колесо фортуни</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body {
                text-align: center;
                font-family: 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, #1a1a2e, #16213e);
                color: white;
                margin: 0;
                padding: 50px 20px;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
            }
            h1 { font-size: 2.5em; margin-bottom: 20px; text-shadow: 0 0 20px #ff6b6b; }
            .number {
                font-size: 90px;
                font-weight: 900;
                background: rgba(255, 107, 107, 0.2);
                padding: 20px 40px;
                border-radius: 50px;
                display: inline-block;
                margin: 30px 0;
                min-width: 150px;
                border: 3px solid #ff6b6b;
                box-shadow: 0 0 40px rgba(255, 107, 107, 0.3);
                transition: all 0.3s;
            }
            .number.spinning { animation: pulse 0.5s infinite alternate; }
            @keyframes pulse {
                0% { transform: scale(1); }
                100% { transform: scale(1.05); }
            }
            button {
                padding: 18px 50px;
                font-size: 24px;
                font-weight: bold;
                border: none;
                border-radius: 50px;
                background: #ff6b6b;
                color: white;
                cursor: pointer;
                transition: all 0.2s;
                box-shadow: 0 8px 25px rgba(255, 107, 107, 0.4);
            }
            button:active { transform: scale(0.95); }
            .hint { margin-top: 30px; font-size: 1.1em; opacity: 0.7; }
        </style>
    </head>
    <body>
        <h1>🎰 Колесо фортуни</h1>
        <div id="result" class="number">❓</div>
        <button id="spin-btn">Крутити!</button>
        <div class="hint">Натисніть, щоб дізнатися свій номер</div>

        <script>
            let tg = window.Telegram.WebApp;
            tg.expand();
            tg.ready();

            let isSpinning = false;
            
            // Привязываем клик через слушатель событий
            document.getElementById('spin-btn').addEventListener('click', function() {
                if (isSpinning) return;
                isSpinning = true;
                const resultDiv = document.getElementById('result');
                resultDiv.classList.add('spinning');
                resultDiv.textContent = '...';

                let count = 0;
                const interval = setInterval(() => {
                    const randomNum = Math.floor(Math.random() * 9000) + 1000;
                    resultDiv.textContent = randomNum;
                    count++;
                    if (count > 15) {
                        clearInterval(interval);
                        const finalNum = Math.floor(Math.random() * 9000) + 1000;
                        resultDiv.textContent = finalNum;
                        resultDiv.classList.remove('spinning');
                        isSpinning = false;

                        document.querySelector('.hint').textContent = '✅ Відправляємо результат...';

                        if (tg) {
                            tg.sendData(JSON.stringify({ number: finalNum }));
                            setTimeout(() => {
                                tg.close();
                            }, 1000);
                        } else {
                            alert("Помилка: не вдалося зв'язатися з Telegram");
                        }
                    }
                }, 100);
            });
        </script>
    </body>
    </html>
    """

# ---------- ДАШБОРД ----------
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if tasks_sheet is None:
        return HTMLResponse("<h1>Ошибка: лист Tasks не найден</h1>", status_code=500)

    tasks = tasks_sheet.get_all_records()
    total_in_progress = sum(1 for t in tasks if str(t.get('Status', '')).strip() == 'in_progress')
    total_new = sum(1 for t in tasks if str(t.get('Status', '')).strip() == 'new')

    drop_map = {}
    if drops_sheet is not None:
        try:
            drops_rows = drops_sheet.get_all_values()
            for row in drops_rows[1:]:
                if len(row) >= 3:
                    name = str(row[0]).strip()
                    tg_id = str(row[2]).strip()
                    username = str(row[3]).strip() if len(row) > 3 else ""
                    if name and tg_id:
                        drop_map[name] = {"id": tg_id, "username": username}
        except Exception as e:
            logger.error(f"Ошибка чтения Drops: {e}")

    category_names = []
    if categories_sheet is not None:
        try:
            cat_records = categories_sheet.get_all_records()
            for row in cat_records:
                cat_val = row.get('Name') or row.get('Project') or list(row.values())[0]
                if cat_val:
                    category_names.append(str(cat_val).strip())
        except Exception as e:
            logger.error(f"Ошибка чтения Categories: {e}")
    
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
            pay_str = f"<b>{html.escape(str(pay))} грн</b>" if pay else "—"
            
            assignee_raw = str(task.get('Assignee', '')).strip()
            names_html = []
            links_html = []
            if assignee_raw:
                for name in assignee_raw.split(', '):
                    safe_name = html.escape(name)
                    names_html.append(f"👤 {safe_name}")
                    if name in drop_map:
                        u_info = drop_map[name]
                        if u_info["username"]:
                            chat_link = f'https://t.me/{html.escape(u_info["username"])}'
                        else:
                            chat_link = f'tg://user?id={html.escape(u_info["id"])}'
                        links_html.append(f'<a href="{chat_link}" target="_blank" class="btn btn-sm btn-success py-0 px-2" title="Написать">💬 ТГ</a>')
                    else:
                        links_html.append('<span class="text-muted small">—</span>')
                assignee_display = "<br>".join(names_html)
                links_display = "<br>".join(links_html)
            else:
                assignee_display = "—"
                links_display = "—"
            
            title_safe = html.escape(str(task.get('Title', '')))
            desc_safe = html.escape(str(task.get('Description', '')))
            
            res += f"""
                <tr class="{row_class}">
                    <td>#{task_id}</td>
                    <td><b>{title_safe}</b><br><small class="text-muted">{desc_safe}</small></td>
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
                    <h5 class="mb-0">📁 {html.escape(cat)} ({len(cat_tasks)})</h5>
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
    if tasks_sheet is None:
        return RedirectResponse(url="/", status_code=303)
    rows = tasks_sheet.get_all_records()
    for idx, row in enumerate(rows, start=2):
        if str(row.get("id")) == str(task_id):
            tasks_sheet.update_cell(idx, 4, "done")
            break
    return RedirectResponse(url="/", status_code=303)

@app.post("/update-phone")
async def update_phone(tg_id: str = Form(...), phone: str = Form(...)):
    if drops_sheet is not None:
        try:
            drops_rows = drops_sheet.get_all_values()
            for idx, row in enumerate(drops_rows, start=1):
                if len(row) >= 3 and str(row[2]) == tg_id:
                    drops_sheet.update_cell(idx, 2, phone)
                    break
        except Exception as e:
            logger.error(f"Ошибка обновления телефона: {e}")
    return RedirectResponse(url="/drops", status_code=303)

@app.post("/update-adequacy")
async def update_adequacy(tg_id: str = Form(...), status: str = Form(...)):
    if drops_sheet is not None:
        try:
            drops_rows = drops_sheet.get_all_values()
            for idx, row in enumerate(drops_rows, start=1):
                if len(row) >= 3 and str(row[2]) == tg_id:
                    drops_sheet.update_cell(idx, 5, status)
                    break
        except Exception as e:
            logger.error(f"Ошибка обновления адекватности: {e}")
    return RedirectResponse(url="/drops", status_code=303)

@app.get("/promo-setup", response_class=HTMLResponse)
async def promo_setup(request: Request):
    if promo_sheet is None:
        return HTMLResponse("<h1>Ошибка: лист Promo не найден</h1>", status_code=500)

    promo_rows = promo_sheet.get_all_values()
    if promo_rows and promo_rows[0] and any(col.strip() for col in promo_rows[0]):
        promo_rows = promo_rows[1:]
    else:
        promo_rows = []

    rows_html = ""
    for r in promo_rows:
        if len(r) < 3:
            continue
        date_reg = r[0] if len(r) > 0 else ""
        name = r[2] if len(r) > 2 else "Без имени"
        uname = r[3] if len(r) > 3 else ""
        ticket = r[4] if len(r) > 4 else ""
        
        if uname:
            chat_link = f'<a href="https://t.me/{html.escape(uname)}" target="_blank">@{html.escape(uname)}</a>'
        else:
            chat_link = "—"

        rows_html += f"<tr><td>{html.escape(date_reg)}</td><td><b>{html.escape(name)}</b><br><small>{chat_link}</small></td><td><span class='badge bg-success fs-6'>{html.escape(ticket)}</span></td></tr>"

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
                [InlineKeyboardButton(
                    text="🎰 Взяти участь в акції",
                    url=f"https://t.me/{BOT_USERNAME}?start=promo"
                )]
            ]
        )
        await bot.send_message(chat_id=GROUP_ID, text=text, reply_markup=keyboard)
        logger.info("✅ Акция успешно отправлена в группу!")
    except Exception as e:
        logger.error(f"❌ ОШИБКА ОТПРАВКИ В ТЕЛЕГРАМ: {e}")
    finally:
        await bot.session.close()
    return RedirectResponse(url="/", status_code=303)

@app.get("/drops", response_class=HTMLResponse)
async def drops_page(request: Request):
    rows_html = ""
    
    if drops_sheet is not None:
        try:
            drops_rows = drops_sheet.get_all_values()
            for row in drops_rows[1:]:
                if len(row) < 3:
                    continue
                u_name = row[0] if len(row) > 0 else "Без имени"
                u_phone = row[1] if len(row) > 1 else ""
                u_id = row[2] if len(row) > 2 else ""
                u_username = row[3] if len(row) > 3 else ""
                adequacy = row[4] if len(row) > 4 else "Средний"
                
                projects = row[5:] if len(row) > 5 else []
                projects = [p for p in projects if p.strip()] 
                
                badges = " ".join([f'<span class="badge bg-info text-dark">{html.escape(p)}</span>' for p in projects])
                if not badges:
                    badges = '<span class="text-muted small">Нет проектов</span>'
                
                if u_username:
                    tg_link = f'<a href="https://t.me/{html.escape(u_username)}" target="_blank" class="btn btn-sm btn-success fw-bold">💬 Написать в ТГ</a>'
                elif u_id:
                    tg_link = f'<a href="tg://user?id={html.escape(u_id)}" target="_blank" class="btn btn-sm btn-success fw-bold">💬 Написать в ТГ</a>'
                else:
                    tg_link = '—'
                
                if adequacy == "Адекватный":
                    row_bg = "table-success"
                elif adequacy == "Неадекватный":
                    row_bg = "table-danger"
                else:
                    row_bg = "table-warning"
                
                rows_html += f"""
                    <tr class="{row_bg}">
                        <td><b>{html.escape(u_name)}</b><br><small class="text-muted">@{html.escape(u_username)} (ID: {html.escape(u_id)})</small></td>
                        <td>
                            <form action="/update-phone" method="post" class="d-flex" style="max-width: 220px;">
                                <input type="hidden" name="tg_id" value="{html.escape(u_id)}">
                                <input type="text" name="phone" class="form-control form-control-sm me-1" value="{html.escape(u_phone)}" placeholder="+380...">
                                <button type="submit" class="btn btn-sm btn-outline-secondary" title="Сохранить">💾</button>
                            </form>
                        </td>
                        <td>
                            <form action="/update-adequacy" method="post">
                                <input type="hidden" name="tg_id" value="{html.escape(u_id)}">
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
        except Exception as e:
            logger.error(f"Ошибка при построении страницы Drops: {e}")

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
    if categories_sheet is not None:
        try:
            for row in categories_sheet.get_all_records():
                cat_val = row.get('Name') or row.get('Project') or list(row.values())[0]
                if cat_val:
                    category_options += f'<option value="{html.escape(str(cat_val))}">{html.escape(str(cat_val))}</option>'
        except Exception as e:
            logger.error(f"Ошибка чтения Categories: {e}")

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
    if tasks_sheet is None:
        return HTMLResponse("<h1>Ошибка: лист Tasks не найден</h1>", status_code=500)

    bot = Bot(token=TOKEN)
    task_id = get_next_task_id()
    clean_category = category.strip()
    msg_header = f"🔥 <b>{clean_category}</b>"
    msg_payment = f"💰💰 <b>Оплата: {payment.strip()} грн</b> 💰💰"
    message_text = f"{msg_header}\n\n{description.strip()}\n\n{msg_payment}"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять в работу", callback_data=f"take_{task_id}")]
        ]
    )

    try:
        message = await bot.send_message(
            chat_id=GROUP_ID,
            text=message_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        tasks_sheet.append_row([
            task_id,
            clean_category,
            description.strip(),
            "new",
            "",
            message.message_id,
            payment.strip()
        ])
        logger.info(f"Задача #{task_id} создана и опубликована")
    except Exception as e:
        logger.error(f"Ошибка при создании задачи: {e}")
        return HTMLResponse(f"<h1>Ошибка: {html.escape(str(e))}</h1>", status_code=500)
    finally:
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

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
