import os
import json

def load_config(path='config.json'):
    if not os.path.exists(path):
        print(f"Config file {path} not found. Please create it based on config.json.example")
        exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_json(name):
    if not os.path.exists(f"{name}.json"):
        return {}
    with open(f"{name}.json", "r", encoding="utf-8") as read_file:
        return json.load(read_file)

def save_json(name, data):
    with open(f"{name}.json", "w", encoding="utf-8") as write_file:
        json.dump(data, write_file, ensure_ascii=False, indent=4)
