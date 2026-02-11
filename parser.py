import re
import csv

# Сюда вставляем текст от поставщика (между тройными кавычками)
RAW_TEXT = """
Air 256 Cloud White eSim - 74500
Air 256 Light gold eSim - 72000
Air 1Tb Sky blue eSim - 99500
🔋17 256 Black eSim - 67000
🔋17 Pro Max 1Tb Silver eSim - 133500
📲17 Pro Max 2Tb Silver Nano + eSim - 178000
🔥 Чехол Air Case with MagSafe Frost - 4500
"""

def parse_price_list(text):
    results = []
    
    # Разделяем на строки
    lines = text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or "🔋 eSim" in line or "Nano + eSim" in line:
            continue # Пропускаем заголовки и пустые строки

        # 1. Сначала вытаскиваем ЦЕНУ (все цифры после тире)
        price_match = re.search(r'-\s*(\d+)$', line)
        if not price_match:
            continue
        price = price_match.group(1)
        
        # Убираем цену из строки для дальнейшего разбора
        content = line[:price_match.start()].strip()
        
        # Очищаем от мусорных иконок в начале
        content = re.sub(r'^[🔋📲🔥❇️]\s*', '', content)

        # 2. Определяем категорию (Чехол или Телефон)
        if "Чехол" in content or "Case" in content:
            category = "Accessories"
            # Для чехлов всё остальное - это название
            model_name = content
            memory = "-"
            color = "-"
            sim = "-"
            
            # Попробуем вытащить цвет (обычно в конце после тире или перед ценой)
            # В вашем примере: "Case... - Black - 5500". Скрипт выше уже отсек цену.
            # Осталось "Case... - Black".
            if " - " in model_name:
                parts = model_name.rsplit(" - ", 1)
                model_name = parts[0]
                color = parts[1]
                
        else:
            category = "iPhone"
            # 3. Парсим ТЕЛЕФОНЫ
            # Ищем память (256, 512, 1Tb, 2Tb)
            mem_match = re.search(r'\b(128|256|512|1Tb|2Tb)\b', content)
            
            if mem_match:
                memory = mem_match.group(1)
                # Добавляем GB если нет (для красоты)
                if "Tb" not in memory: memory += " GB"
                
                # Всё ДО памяти - это Модель
                model_part = content[:mem_match.start()].strip()
                
                # Всё ПОСЛЕ памяти - это Цвет и SIM
                rest = content[mem_match.end():].strip()
                
                # Ищем SIM (eSim или Nano + eSim)
                sim_match = re.search(r'(Nano \+ eSim|eSim)', rest)
                if sim_match:
                    sim = sim_match.group(1)
                    # Цвет - это то, что между памятью и SIM
                    color = rest[:sim_match.start()].strip()
                else:
                    sim = "Unknown"
                    color = rest
            else:
                # Если память не нашли, кидаем всё в название
                model_name = content
                memory = "?"
                color = "?"
                sim = "?"
                model_part = content

            # Нормализация названия модели
            if model_part.startswith("17"):
                model_name = "iPhone " + model_part
            elif model_part.startswith("Air"):
                model_name = "iPhone 17 Air" # Или как правильно называется модель
            else:
                model_name = model_part

        # Генерируем ID (SKU)
        sku = f"{model_name[:5]}-{memory}-{color[:3]}".replace(" ", "").upper()

        results.append({
            "id": sku,
            "title": f"{model_name} {memory} {color} {sim}",
            "price": price,
            "brand": "Apple",
            "bot_model_group": model_name, # Для меню
            "memory": memory,
            "color": color,
            "sim": sim,
            "availability": "in stock"
        })

    return results

# Запуск
parsed_data = parse_price_list(RAW_TEXT)

# Сохранение в CSV
with open('import_to_google.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=["id", "title", "price", "brand", "bot_model_group", "memory", "color", "sim", "availability"])
    writer.writeheader()
    writer.writerows(parsed_data)

print(f"✅ Готово! Обработано {len(parsed_data)} товаров. Файл import_to_google.csv создан.")
print("Теперь скачайте его и скопируйте данные в Google Таблицу.")
