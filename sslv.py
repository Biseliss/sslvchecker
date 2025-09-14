import requests
import xml.etree.ElementTree as ET
import jsonrw
from bs4 import BeautifulSoup
from bs4.element import NavigableString
import re
import tldextract

data = jsonrw.load_json("sslv")

if not data:
    data = {
        "url_base": "https://www.ss.lv/ru/",
        "last_lookup": []
    }


class Item:
    def __init__(self, title, link, pubDate, description):
        self.title = title
        self.link = link
        self.pubDate = pubDate
        self.description = description
        self.image_url = ""
        self.attributes = {}
        self._parse_description()

    def _parse_description(self):
        """Универсально извлекает:
        - image_url (первая <img ... src="...")
        - пары Label: <b>Value</b> независимо от набора полей
        Результат сохраняется в self.attributes (dict)
        Без хардкода по категориям: логика опирается только на структуру HTML.
        """
        if not self.description:
            return
        try:
            soup = BeautifulSoup(self.description, 'html.parser')
        except Exception:
            return

        # Картинка
        img = soup.find('img')
        if img and img.get('src'):
            self.image_url = img['src'].strip()

        attrs: dict[str, str] = {}

        # Подход 1: искать текстовые узлы заканчивающиеся на ':' и ближайший <b> после них
        for node in soup.descendants:
            if isinstance(node, NavigableString):
                raw = str(node)
                text = raw.strip()
                if not text or not text.endswith(':'):
                    continue
                label = text[:-1].strip()  # убрать двоеточие
                if not label:
                    continue
                value = None
                # пройти по соседям в пределах одного "контекста"
                for sib in node.next_siblings:
                    # пропускаем пустые строки / пробелы
                    if isinstance(sib, NavigableString):
                        if sib.strip():
                            # Иногда значение может быть прямо текстом без <b>, зафиксируем
                            if value is None:
                                value_candidate = sib.strip()
                                # Если сразу перенос строки (<br>) не встретился – можно принять
                                if value_candidate:
                                    value = value_candidate
                            continue
                    else:
                        name = getattr(sib, 'name', None)
                        if name == 'b':
                            value_text = sib.get_text(separator=' ', strip=True)
                            if value_text:
                                value = value_text
                                break
                        elif name in ('br', 'div', 'p'):  # дошли до разделителя – прекращаем поиск значения
                            break
                if value:
                    # Если такой label уже есть – не перетираем, но можно конкатенировать
                    if label in attrs and attrs[label] != value:
                        attrs[label] = f"{attrs[label]} | {value}"
                    else:
                        attrs[label] = value

        # Подход 2 (fallback): если не нашли ничего первый способ
        if not attrs:
            text_blocks = soup.get_text(separator='\n')
            for line in text_blocks.splitlines():
                line = line.strip()
                if not line:
                    continue
                m = re.match(r'^([^:]+):\s*(.+)$', line)
                if m:
                    label = m.group(1).strip()
                    value = m.group(2).strip()
                    if label and value and label not in attrs:
                        attrs[label] = value

        self.attributes = attrs
        raw_price = self.attributes.get("Цена", "")
        cleaned_price = re.sub(r'[^0-9.]', '', raw_price.replace(',', '').replace('\u00a0', ''))
        self.price = float(cleaned_price) if cleaned_price else None

    def __repr__(self):
        return f"Item(title={self.title!r}, link={self.link!r}, pubDate={self.pubDate!r}, image_url={self.image_url!r}, attributes={self.attributes!r})"


def fetch_rss(url):
    response = requests.get(url)
    response.raise_for_status()
    if response.headers.get('Content-Type').split(';')[0] != 'text/xml':
        raise ValueError("URL does not point to a valid RSS feed")
    return response.content


def parse_rss(xml_data):
    root = ET.fromstring(xml_data)
    channel = root.find('channel')
    items = []
    if channel is None:
        return items
    for item in channel.findall('item'):
        title_el = item.find('title')
        link_el = item.find('link')
        date_el = item.find('pubDate')
        description_el = item.find('description')
        title = title_el.text if title_el is not None else ''
        link = link_el.text if link_el is not None else ''
        pub_date = date_el.text if date_el is not None else ''
        description = description_el.text if description_el is not None else ''
        if link:
            items.append({
                'title': title,
                'link': link,
                'pubDate': pub_date,
                'description': description,
            })
    return items


def fetch_new(page_items):
    # от новых к старым
    new_items = []
    for item in page_items:
        if extract_id(item['link']) in data['last_lookup']:
            break
        new_items.append(item)
    return new_items


def parse_item(item):
    return Item(
        title=item['title'],
        link=item['link'],
        pubDate=item['pubDate'],
        description=item['description']
    )


def extract_id(link: str):
    return link.split('/')[-1].split('.')[0]


def extract_path(url: str) -> str:
    if not url.startswith(('http://', 'https://')):
        url = data['url_base'] + url.lstrip('/')
    extracted = tldextract.extract(url)
    if extracted.domain != "ss" or extracted.suffix not in ["lv", "com"]:
        raise ValueError("URL does not belong to ss.lv domain")
    path = url.split(extracted.suffix + '/')[1]
    path = path.rstrip('/').replace('/msg/', '/')
    path = "/".join(path.split('/')[1:])
    return path


def is_valid_path(path: str) -> bool:
    url = data['url_base'] + path + '/rss/'
    extracted = tldextract.extract(url)
    domain = extracted.domain == "ss" and extracted.suffix in ["lv", "com"]
    if not domain:
        return False
    resp = requests.head(url, allow_redirects=True, timeout=5)
    return resp.status_code == 200 and resp.headers.get('Content-Type').split(';')[0] == 'text/xml'


def fetch_all_new(pages: list[str]):
    all_items = []
    result = {}
    for page in pages:
        result[page] = []
        page_items = parse_rss(fetch_rss(data['url_base'] + page + '/rss/'))
        all_items.extend(extract_id(item['link']) for item in page_items)
        result[page] = [parse_item(item) for item in fetch_new(page_items)]
    data['last_lookup'] = all_items
    jsonrw.save_json("sslv", data)
    return result


def first_lookup(page: str):
    page_items = parse_rss(fetch_rss(data['url_base'] + page + '/rss/'))
    all_items = [extract_id(item['link']) for item in page_items]
    data['last_lookup'].extend(all_items)
    jsonrw.save_json("sslv", data)
