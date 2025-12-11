# 4. Обработка выбора конкретной модели (начинается с item_)
@dp.callback_query(F.data.startswith("item_"))
async def item_selection(callback: types.CallbackQuery):
    model_name = callback.data.split("_")[1]
    user_id = callback.from_user.id
    username = callback.from_user.username
    full_name = callback.from_user.full_name
    
    # 1. Отправляем подтверждение пользователю
    await callback.message.answer(
        f"✅ Вы выбрали: **{model_name}**!\n"
        "Ваш запрос передан менеджеру. Он скоро свяжется с вами."
    )
    
    # 2. Формируем сообщение для менеджера
    manager_message = (
        "🔥 **НОВАЯ ЗАЯВКА НА ТЕХНИКУ APPLE!**\n"
        f"**Модель:** `{model_name}`\n"
        "--- Клиент ---\n"
        f"👤 Имя: **{full_name}**\n"
        f"🆔 ID: `{user_id}`\n"
        f"🔗 @{username or 'Нет никнейма'}\n\n"
        f"[Написать клиенту](tg://user?id={user_id})"
    )
    
    # 3. Отправляем уведомление менеджеру
    manager_id = os.getenv('MANAGER_ID')
    if manager_id:
        try:
            await bot.send_message(
                chat_id=manager_id,
                text=manager_message,
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение менеджеру {manager_id}: {e}")
            
    await callback.answer(f"Заявка на {model_name} отправлена!")
