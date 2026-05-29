/**
 * VNX APPLE SHOP - AI ПАРСЕР v15.4 (SMART SYNC)
 * Умная синхронизация: обновляет цены, дозаполняет ЛЮБЫЕ пустые поля, бережёт ручной ввод.
 */

var MODEL_ID = "gemini-2.5-flash";
var HEADERS = [
  "id", "title", "description", "availability", "condition", "price", "link",
  "image_link", "brand", "google_product_category", "fb_product_category",
  "quantity_to_sell_on_facebook", "purchase_price", "sale_price_effective_date",
  "item_group_id", "gender", "color", "size", "age_group", "material",
  "pattern", "shipping", "shipping_weight", "gtin", "memory", "sim", "region"
];
// purchase_price (col M) = закупочная цена без наценки
// price          (col F) = продажная цена с наценкой (видит покупатель)

function onOpen() {
  SpreadsheetApp.getUi().createMenu('🍏 AI ПАРСЕР')
      .addItem('🧹 1. ОЧИСТИТЬ IMPORT', 'clearImportSheet')
      .addItem('🚀 2. ЗАПУСТИТЬ ПАРСИНГ (JSON)', 'processWithAutoModel')
      .addItem('🔄 3. СИНХРОНИЗИРОВАТЬ ПРАЙС', 'syncWithCatalog')
      .addToUi();
}

function processWithAutoModel() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.toast("Чтение текста для парсинга...", "⚙️ Этап 1/4", 5);

  var draftSheet = ss.getSheetByName("Draft");
  var importSheet = ss.getSheetByName("Import");

  var rawKey = PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY');
  if (!rawKey) return alert("ОШИБКА: Ключ не найден.");
  var cleanKey = rawKey.replace(/[^a-zA-Z0-9-]/g, "");

  var rawText = draftSheet.getRange(1, 1, draftSheet.getLastRow(), 1).getValues()
                 .filter(r => r[0]).map(r => r[0]).join("\n");

  if (!rawText) return alert("Лист Draft пуст!");

  ss.toast("Подготовка запроса к ИИ...", "⚙️ Этап 2/4", 5);

  var url = "https://generativelanguage.googleapis.com/v1/models/" + MODEL_ID + ":generateContent?key=" + cleanKey;

  var prompt = "Ты — строгий API. Верни ТОЛЬКО валидный JSON-массив объектов.\n" +
               "Каждый объект должен содержать ключи: " + HEADERS.join(", ") + ".\n\n" +
               "ПРАВИЛА:\n" +
               "1. id: оставь пустой строкой '' (я сгенерирую его сам).\n" +
               "2. title: полное чистое название товара (СТРОГО БЕЗ эмодзи и флагов).\n" +
               "3. availability: 'in stock'.\n" +
               "4. condition: 'new'.\n" +
               "5. brand: 'Apple'.\n" +
               "6. price: только цифры.\n" +
               "7. memory, sim, region, color, item_group_id: вытащи из текста.\n" +
               "8. image_link: попытайся найти или сгенерировать прямую HTTPS ссылку на официальное фото этого товара (Apple). Если не можешь, ставь '-'.\n" +
               "9. ОСТАЛЬНЫЕ ключи должны содержать строго строку '-'.\n" +
               "10. ВАЖНО: НИКАКИХ эмодзи-кружков и флагов в title, color, memory!\n" +
               "11. РЕГИОНЫ: Слово 'International' ЗАПРЕЩЕНО. Используй логику по SIM: 2 eSIM = 'Америка', Nano+eSIM = 'Европа' (или Азия), 2 физические Nano = 'Китай'. Если сомневаешься — ставь '-'.\n\n" +
               "ТЕКСТ:\n" + rawText;

  var payload = {
    "contents": [{ "parts": [{ "text": prompt }] }],
    "generationConfig": { "temperature": 0.0 }
  };

  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };

  try {
    ss.toast("Ожидание ответа от Gemini. Это может занять 5-15 секунд...", "⏳ Этап 3/4", 20);

    var response = UrlFetchApp.fetch(url, options);
    var json = JSON.parse(response.getContentText());

    if (json.error) return alert("Ошибка Google: " + json.error.message);

    if (json.candidates && json.candidates[0].content) {
      ss.toast("Данные получены. Формируем таблицу...", "🛠 Этап 4/4", 5);

      var aiOutput = json.candidates[0].content.parts[0].text;
      renderJsonToSheet(aiOutput, importSheet);
      ss.toast("JSON разобран. Проверьте лист Import и нажмите Синхронизировать.", "✅ УСПЕХ!", 10);
    } else {
      alert("Ошибка ответа AI.");
    }
  } catch (e) { alert("Ошибка связи: " + e.message); }
}

function renderJsonToSheet(jsonString, sheet) {
  try {
    var cleanJson = jsonString.replace(/```json/gi, "").replace(/```/g, "").replace(/[🔴🔵🟢🟡🟣⚫⚪🟤]/g, "").trim();

    var startIndex = cleanJson.indexOf('[');
    var endIndex = cleanJson.lastIndexOf(']');
    if (startIndex !== -1 && endIndex !== -1) {
        cleanJson = cleanJson.substring(startIndex, endIndex + 1);
    }

    var parsedData = JSON.parse(cleanJson);
    var table = [];

    if (!Array.isArray(parsedData)) parsedData = [parsedData];

    parsedData.forEach(function(item) {
      var row = [];
      HEADERS.forEach(function(header) {
        var val = item[header];

        // === ФИКС FACEBOOK COMMERCE ===
        if (header === "google_product_category") {
            row.push("Electronics");
            return;
        }

        // Автоматизируем ссылку
        if (header === "link") {
            row.push("https://www.apple.com");
            return;
        }
        // ==============================

        if (val === undefined || val === null || val === "-" || val === " - " || val === "") {
            row.push("");
        } else {
            if (typeof val === "string") {
                if (header === "title") {
                    val = val.replace(/[\uD83C][\uDDE6-\uDDFF][\uD83C][\uDDE6-\uDDFF]/g, "").trim();
                }
                if (header === "region" && val.toUpperCase().includes("INTERNATIONAL")) {
                    val = "-";
                }
            }
            row.push(val);
        }
      });

      var generatedId = generateDeterministicId(row[14], row[24], row[25], row[16], row[26]);
      row[0] = generatedId;

      table.push(row);
    });

    if (table.length > 0) {
      sheet.clear();
      sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight("bold").setBackground("#45818e").setFontColor("white");
      sheet.getRange(2, 1, table.length, HEADERS.length).setValues(table);
      sheet.autoResizeColumns(1, HEADERS.length);
    }
  } catch (e) {
    SpreadsheetApp.getUi().alert("Ошибка разбора JSON: " + e.message);
  }
}

function generateDeterministicId(group, memory, sim, color, region) {
  var clean = function(str) {
    var text = (str || "").toString();

    // Конвертируем флаги-эмодзи в буквы
    text = Array.from(text).map(function(char) {
      var code = char.codePointAt(0);
      if (code >= 127462 && code <= 127487) {
        return String.fromCharCode(code - 127462 + 65);
      }
      return char;
    }).join('');

    return text.toUpperCase().replace(/[^A-Z0-9А-Я]/g, "");
  };

  var g = clean(group);
  var m = clean(memory);
  var s = clean(sim);
  var c = clean(color);
  var r = clean(region);

  return [g, m, s, c, r].filter(Boolean).join("-");
}

function calculateMarkup(rawPrice) {
  var price = parseFloat(rawPrice);
  if (isNaN(price) || price <= 0) return rawPrice;

  if (price < 30000)       return price + 2000;
  else if (price < 40000)  return price + 3000;
  else if (price < 80000)  return price + 4000;
  else if (price < 100000) return price + 5000;
  else if (price < 140000) return price + 6000;
  else if (price < 200000) return price + 7000;
  else                     return price + 8000;
  // Аксессуары обрабатываются отдельно (+20%) через calculate_markup_accessory в Python
}

function syncWithCatalog() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var importSheet = ss.getSheetByName("Import");

  if (!importSheet || importSheet.getLastRow() < 2) {
    return alert("Лист Import пуст или не найден. Сначала запустите парсинг.");
  }

  var response = ui.prompt("Синхронизация каталога. Введите название целевого листа (например: Main, iPad, iPhone):", ui.ButtonSet.OK_CANCEL);

  if (response.getSelectedButton() !== ui.Button.OK) return;

  var targetName = response.getResponseText().trim();
  var targetSheet = ss.getSheetByName(targetName);

  if (!targetSheet) {
    return alert("❌ Ошибка: Лист '" + targetName + "' не найден!");
  }

  ss.toast("Анализ существующих позиций...", "🔄 Синхронизация", 5);

  var importData = importSheet.getDataRange().getValues();
  var targetData = targetSheet.getDataRange().getValues();

  var targetIdMap = {};
  for (var i = 1; i < targetData.length; i++) {
    var id = targetData[i][0];
    if (id) targetIdMap[id] = i;
  }

  var updatedCount = 0;
  var addedCount = 0;
  var newRows = [];

  for (var j = 1; j < importData.length; j++) {
    var importRow = importData[j];
    var importId = importRow[0];
    var rawPrice = importRow[5];

    if (!importId || importId === "" || importId === "-") continue;

    var finalPrice = calculateMarkup(rawPrice);
    importRow[5] = finalPrice;

    if (targetIdMap.hasOwnProperty(importId)) {
      var targetRowIndex = targetIdMap[importId];
      var targetRowData = targetData[targetRowIndex];
      var rowModified = false;

      while (targetRowData.length < HEADERS.length) {
          targetRowData.push("");
      }

      if (targetRowData[5] !== finalPrice) {
          targetRowData[5] = finalPrice;
          rowModified = true;
      }

      for (var col = 1; col < HEADERS.length; col++) {
        if (col === 5) continue;

        var currentVal = targetRowData[col];
        var importVal = importRow[col];

        var isCurrentEmpty = (currentVal === undefined || currentVal === null || currentVal === "" || currentVal === "-" || currentVal === " - " || currentVal.toString().trim() === "");
        var isImportValid = (importVal !== undefined && importVal !== null && importVal !== "" && importVal !== "-" && importVal !== " - " && importVal.toString().trim() !== "");

        if (isCurrentEmpty && isImportValid) {
          targetRowData[col] = importVal;
          rowModified = true;
        }
      }

      if (rowModified) {
         targetSheet.getRange(targetRowIndex + 1, 1, 1, HEADERS.length).setValues([targetRowData]);
         updatedCount++;
      }
    } else {
      var newRow = importRow.slice(0, HEADERS.length);
      while (newRow.length < HEADERS.length) {
          newRow.push("");
      }
      newRows.push(newRow);
      addedCount++;
    }
  }

  ss.toast("Запись новых данных в каталог...", "💾 Сохранение", 5);

  if (newRows.length > 0) {
    var lastTargetRow = targetSheet.getLastRow();
    if (lastTargetRow === 0) {
      targetSheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
      lastTargetRow = 1;
    }
    targetSheet.getRange(lastTargetRow + 1, 1, newRows.length, HEADERS.length).setValues(newRows);
  }

  SpreadsheetApp.getActiveSpreadsheet().toast("Обновлено существующих: " + updatedCount + ", Добавлено новых: " + addedCount + ".", "✅ Успешно!", 10);

  clearImportSheet(true);
}

function clearImportSheet(silent) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName("Import");
  if (sheet) {
    sheet.clear();
    sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight("bold").setBackground("#45818e").setFontColor("white");
    if (!silent) {
      ss.toast("Лист Import успешно очищен и готов к новой работе.", "🧹 Очистка", 3);
    }
  }
}

function alert(msg) { SpreadsheetApp.getUi().alert(msg); }
