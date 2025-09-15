import json
import logging
import os
import telebot
from telebot import types
import sslv
import threading
import time
import html
import jsonrw

def load_config(path='config.json'):
    if not os.path.exists(path):
        print(f"Config file {path} not found. Please create it based on config.json.example")
        exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


config = load_config()
data = jsonrw.load_json("data")
TOKEN = config.get('token')
ADMINS = set(config.get('admins', []))
CHANNEL_PREFERENCES = config.get('channel_preferences', {})

if not TOKEN:
    print("Bot token not specified in config.json")
    exit(1)

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')

data_lock = threading.Lock()

logging.basicConfig(level=logging.INFO)


def format_item(page: str, item: sslv.Item) -> tuple[str, str | None]:
    title = html.escape(item.title)
    link = html.escape(item.link)
    attr_lines = []
    for k, v in item.attributes.items():
        k_esc = html.escape(k)
        v_esc = html.escape(v)
        attr_lines.append(f"<b>{k_esc}:</b> {v_esc}")
    attrs_block = "\n".join(attr_lines)
    header = f"<b>{title}</b>\n"
    page_line = f"Категория: <code>{html.escape(page)}</code>\n"
    link_line = f"<a href=\"{link}\">Открыть объявление</a>"
    body = "\n".join(x for x in [header, page_line, attrs_block, link_line] if x.strip())
    if item.image_url:
        if len(body) > 1000:
            body = body[:995] + '…'
        return body, item.image_url
    return body, None


def send_item_to_subscribers(page: str, item: sslv.Item):
    text, image_url = format_item(page, item)
    with data_lock:
        chats = list(data)
    for chat_id in chats:
        if page not in data[chat_id]["paths"]:
            continue
        try:
            if not item.price or item.price < data[chat_id]["paths"][page]["price_min"] or (data[chat_id]["paths"][page]["price_max"] != 0 and item.price > data[chat_id]["paths"][page]["price_max"]):
                continue
        except Exception:
            pass
        try:
            if image_url:
                bot.send_photo(chat_id, image_url, caption=text)
            else:
                bot.send_message(chat_id, text, disable_web_page_preview=False)
        except Exception as e:
            logging.exception(f"Ошибка отправки сообщения chat_id={chat_id}")


def monitor_loop(interval_sec: int = config['interval']):
    logging.info("Старт фонового мониторинга объявлений")
    while True:
        try:
            with data_lock:
                pages = {p for obj in data.values() for p in obj["paths"]}
            if pages:
                new_by_page = sslv.fetch_all_new(pages)
                for page, items in new_by_page.items():
                    if not items:
                        continue
                    for it in reversed(items):
                        send_item_to_subscribers(page, it)
        except Exception:
            logging.exception("Ошибка в цикле мониторинга")
        time.sleep(interval_sec)


@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.send_message(message.chat.id, "Вас приветствует бот для мониторинга новых объявлений SS.LV!\nДля начала, пожалуйста, используйте команду /monitor &lt;путь_категории&gt; (например, \"https://www.ss.lv/msg/ru/transport/cars/honda\" или \"transport/cars/honda\")\nНаписано на Python3, Telegram API pytelegrambotapi\nСделано в 2025, https://vmartin.codead.dev/sslvcheckerbot/")


@bot.message_handler(commands=['help'])
def handle_help(message):
    help_text = (
        "/start - Запустить бота\n"
        "/help - Справка\n"
        "/monitor &lt;путь_категории&gt; - Начать мониторинг указанной категории (например, transport/cars/honda)\n"
        "/monitors - Показать текущие мониторинги\n"
        "/stop &lt;путь_категории&gt; - Остановить мониторинг указанной категории\n"
        "/price &lt;путь_категории&gt; &lt;минимальная_цена&gt; &lt;максимальная_цена&gt; - Установить фильтр по цене для указанной категории (например, /price transport/cars/honda 5000 15000). Используйте 0 для снятия ограничения.\n"
    )
    bot.send_message(message.chat.id, help_text)


@bot.message_handler(commands=['monitor'])
def handle_monitor(message: types.Message):
    args = message.text.split(" ")
    if len(args) < 2:
        bot.send_message(message.chat.id, "Использование: /monitor &lt;путь_категории&gt;")
        return
    try:
        path = sslv.extract_path(args[1]) if '//' in args[1] else args[1].strip('/').replace('msg/','')
    except Exception:
        bot.send_message(message.chat.id, "Некорректный путь категории (не удалось разобрать ссылку).")
        return
    if not path:
        bot.send_message(message.chat.id, "Пустой путь категории")
        return
    if path in data and message.chat.id in data[path]:
        bot.send_message(message.chat.id, "Вы уже подписаны на эту категорию")
        return
    try:
        valid = sslv.is_valid_path(path)
    except Exception:
        valid = False
    if not valid:
        bot.send_message(message.chat.id, "Некорректный путь категории (не удалось получить содержимое RSS с домена ss.lv). Пример правильного написания: \"https://www.ss.lv/msg/ru/transport/cars/honda\" или \"transport/cars/honda\".")
        return
    with data_lock:
        bot.send_message(message.chat.id, f"Начинаю мониторинг категории: \"{path}\"")
        chat_id = str(message.chat.id)
        if chat_id not in data:
            data[chat_id] = {"paths": {}}
            sslv.first_lookup(path)
        data[str(message.chat.id)]["paths"][path] = {"price_min": 0, "price_max": 0}
        jsonrw.save_json("data", data)


@bot.message_handler(commands=['monitors'])
def handle_monitors(message: types.Message):
    with data_lock:
        if data.get(str(message.chat.id)) is None or not data[str(message.chat.id)]["paths"]:
            bot.send_message(message.chat.id, "У вас нет активных категорий для мониторинга. Используйте /monitor &lt;путь_категории&gt; для добавления.")
            return
        subscribed_pages = list(data[str(message.chat.id)]["paths"])
    txt = "Активные категории:\n" + "\n".join(f"- {p}" for p in subscribed_pages)
    bot.send_message(message.chat.id, txt)


@bot.message_handler(commands=['stop'])
def handle_stop(message: types.Message):
    args = message.text.split(" ")
    if len(args) < 2:
        bot.send_message(message.chat.id, "Использование: /stop &lt;путь_категории&gt;")
        return
    try:
        path = sslv.extract_path(args[1])
    except Exception:
        bot.send_message(message.chat.id, "Некорректный путь категории (не удалось разобрать ссылку).")
        return
    with data_lock:
        if data.get(str(message.chat.id)) is None or path not in data[str(message.chat.id)]["paths"]:
            bot.send_message(message.chat.id, "Вы не подписаны на эту категорию")
            return
        chat_id = str(message.chat.id)
        data[chat_id]["paths"].pop(path)
        if not data[chat_id]["paths"]:
            del data[chat_id]
        jsonrw.save_json("data", data)
    bot.send_message(message.chat.id, f"Мониторинг категории {path} остановлен")


@bot.message_handler(commands=['price'])
def handle_price(message: types.Message):
    args = message.text.split(" ")
    if len(args) < 3:
        bot.send_message(message.chat.id, "Использование: /price &lt;путь_категории&gt; &lt;минимальная_цена&gt; &lt;максимальная_цена&gt;")
        return
    try:
        path = sslv.extract_path(args[1])
        price_min = float(args[2])
        if len(args) < 4:
            price_max = 0
        else:
            price_max = float(args[3])
    except Exception:
        bot.send_message(message.chat.id, "Некорректные параметры.")
        return
    if price_min < 0 or price_max < 0 or (price_max != 0 and price_min > price_max):
        bot.send_message(message.chat.id, "Некорректные значения цены (минимальная и максимальная цена должны быть неотрицательными, максимальная должна быть больше или равна минимальной, или равна 0 для снятия ограничения).")
        return
    with data_lock:
        chat_id = str(message.chat.id)
        if data.get(chat_id) is None or path not in data[chat_id]["paths"]:
            bot.send_message(message.chat.id, "Вы не подписаны на эту категорию")
            return
        chat_id = str(message.chat.id)
        data[chat_id]["paths"][path]["price_min"] = price_min
        data[chat_id]["paths"][path]["price_max"] = price_max
        jsonrw.save_json("data", data)
    bot.send_message(message.chat.id, f"Фильтр по цене для категории {path} установлен: {price_min} - {price_max}")


def main():
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
    try:
        logging.info("Запуск бота")
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except KeyboardInterrupt:
        logging.info("Остановка бота")


if __name__ == '__main__':
    main()
