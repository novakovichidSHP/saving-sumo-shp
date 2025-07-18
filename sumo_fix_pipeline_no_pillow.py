import zipfile
import json
import os
import shutil
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox
import base64
from io import BytesIO
import re

# --- Диалог выбора файла или папки ---
def select_path():
    root = tk.Tk()
    root.withdraw()
    choice = messagebox.askyesno('Выбор', 'Обработать ОДИН файл? (Нет = выбрать папку)')
    if choice:
        file_path = filedialog.askopenfilename(
            title='Выберите .sumo файл',
            filetypes=[('Sumo files', '*.sumo')]
        )
        return file_path, 'file'
    else:
        folder_path = filedialog.askdirectory(title='Выберите папку с .sumo файлами')
        return folder_path, 'folder'

# --- Конвертация sumo -> json + извлечение всех файлов ---
def extract_sumo(sumo_path, temp_dir):
    with zipfile.ZipFile(sumo_path, 'r') as zf:
        zf.extractall(temp_dir)
    data_txt_path = os.path.join(temp_dir, 'data.txt')
    with open(data_txt_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    return json_data

# --- Исправление геометрии ---
def fix_geometry_types(data):
    buffer_to_simple = {
        'BoxBufferGeometry': 'BoxGeometry',
        'PlaneBufferGeometry': 'PlaneGeometry',
        'CylinderBufferGeometry': 'CylinderGeometry',
        'SphereBufferGeometry': 'SphereGeometry',
        'CircleBufferGeometry': 'CircleGeometry',
        'ConeBufferGeometry': 'ConeGeometry',
        'TorusBufferGeometry': 'TorusGeometry',
        'TorusKnotBufferGeometry': 'TorusKnotGeometry',
        'DodecahedronBufferGeometry': 'DodecahedronGeometry',
        'IcosahedronBufferGeometry': 'IcosahedronGeometry',
        'OctahedronBufferGeometry': 'OctahedronGeometry',
        'TetrahedronBufferGeometry': 'TetrahedronGeometry',
        'RingBufferGeometry': 'RingGeometry',
        'LatheBufferGeometry': 'LatheGeometry',
        'TubeBufferGeometry': 'TubeGeometry',
        'EdgesGeometry': 'EdgesGeometry',
    }
    geometries = data.get('data', {}).get('scene', {}).get('geometries', [])
    for geom in geometries:
        t = geom.get('type')
        if t in buffer_to_simple:
            geom['type'] = buffer_to_simple[t]
    return data

# --- Базовая проверка встроенных base64-изображений (без Pillow) ---
def validate_embedded_images_base64(data, temp_dir, original_data=None):
    pattern = re.compile(r'^data:image/([a-zA-Z0-9]+);base64,', re.IGNORECASE)
    found_formats = set()
    checked = 0
    error_images = 0
    def recursive_check(obj, orig_obj=None):
        nonlocal checked, error_images
        if isinstance(obj, dict):
            for k, v in obj.items():
                orig_v = orig_obj[k] if (orig_obj and isinstance(orig_obj, dict) and k in orig_obj) else None
                if isinstance(v, str):
                    m = pattern.match(v)
                    if m:
                        fmt = m.group(1).lower()
                        found_formats.add(fmt)
                        b64data = v.split(',', 1)[1]
                        try:
                            # Просто проверяем, что строка корректно декодируется
                            base64.b64decode(b64data)
                            checked += 1
                        except Exception as e:
                            print(f'Ошибка base64 изображения (format={fmt}): {e}')
                            if orig_v:
                                obj[k] = orig_v
                            error_images += 1
                    else:
                        recursive_check(v, orig_v)
                else:
                    recursive_check(v, orig_v)
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                orig_item = orig_obj[idx] if (orig_obj and isinstance(orig_obj, list) and idx < len(orig_obj)) else None
                recursive_check(item, orig_item)
    recursive_check(data, original_data)
    print(f'Найдено форматов изображений: {found_formats}')
    print(f'Проверено base64-строк: {checked}, ошибок: {error_images}')
    return data

# --- Чистка ссылок на sumo.app/api/auth/check и CORS ---
def clean_auth_references(data):
    skip_keys = {'materials', 'textures', 'images'}
    removed = []
    def recursive_clean(obj, parent_key=None):
        if isinstance(obj, dict):
            keys_to_del = []
            for k, v in obj.items():
                if parent_key in skip_keys:
                    continue  # не трогаем материалы/текстуры/изображения
                if isinstance(v, str) and 'sumo.app/api/auth/check' in v:
                    keys_to_del.append(k)
                else:
                    recursive_clean(v, k)
            for k in keys_to_del:
                removed.append((parent_key, k))
                del obj[k]
        elif isinstance(obj, list):
            for item in obj:
                recursive_clean(item, parent_key)
    recursive_clean(data)
    if removed:
        print('Удалены поля:', removed)
    return data

# --- Сборка sumo-архива из временной папки ---
def build_sumo_from_dir(temp_dir, out_path):
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, temp_dir)
                zf.write(file_path, arcname)

# --- Обработка одного файла ---
def process_file(sumo_path, out_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        # Читаем исходный data.txt для сравнения структуры
        with zipfile.ZipFile(sumo_path, 'r') as zf:
            with zf.open('data.txt') as data_file:
                original_data = json.load(data_file)
        data = extract_sumo(sumo_path, temp_dir)
        data = fix_geometry_types(data)
        data = validate_embedded_images_base64(data, temp_dir, original_data)
        data = clean_auth_references(data)
        # Перезаписываем data.txt
        data_txt_path = os.path.join(temp_dir, 'data.txt')
        with open(data_txt_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        build_sumo_from_dir(temp_dir, out_path)
    print(f'Готово: {out_path}')

# --- Основной процесс ---
def main():
    path, mode = select_path()
    if not path:
        print('Файл или папка не выбраны.')
        return
    if mode == 'file':
        out_path = os.path.splitext(path)[0] + '_fixed.sumo'
        process_file(path, out_path)
        messagebox.showinfo('Готово', f'Файл сохранён: {out_path}')
    else:
        # Папка: обработать все .sumo-файлы, сохранить в подпапку fixed
        out_dir = os.path.join(path, 'fixed')
        os.makedirs(out_dir, exist_ok=True)
        count = 0
        for fname in os.listdir(path):
            if fname.lower().endswith('.sumo'):
                in_path = os.path.join(path, fname)
                out_path = os.path.join(out_dir, os.path.splitext(fname)[0] + '_fixed.sumo')
                process_file(in_path, out_path)
                count += 1
        messagebox.showinfo('Готово', f'Обработано файлов: {count}\nРезультаты в: {out_dir}')

if __name__ == '__main__':
    main() 