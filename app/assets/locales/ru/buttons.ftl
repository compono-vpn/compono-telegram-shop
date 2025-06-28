# Back
btn-back = ⬅️ Назад
btn-back-menu = ⬅️ Вернуться в меню
btn-back-dashboard = ⬅️ Вернуться в панель управления


# Menu
btn-menu-connect = 🚀 Подключиться
btn-menu-subscription = 💳 Подписка
btn-menu-invite = 👥 Пригласить
btn-menu-support = 🆘 Поддержка
btn-menu-dashboard = 🛠 Панель управления


# Dashboard
btn-dashboard-statistics = 📊 Статистика
btn-dashboard-users = 👥 Пользователи
btn-dashboard-broadcast = 📢 Рассылка
btn-dashboard-promocodes = 🎟 Промокоды
btn-dashboard-maintenance = 🚧 Режим обслуживания
btn-dashboard-remnawave = 🌊 RemnaWave
btn-dashboard-remnashop = 🛍 RemnaShop


# Users
btn-users-search = 🔍 Поиск пользователя
btn-users-recent-registered = 🆕 Последние зарегистрированные
btn-users-recent-activity = 📝 Последние взаимодействующие
btn-users-blacklist = 🚫 Чёрный список


# Blacklist
btn-users-unblock-all = 🔓 Разблокировать всех
btn-users-unblock-all-confirm = ✅ Подтвердить


# User
btn-user-statistics = 📊 Статистика
btn-user-message = 📩 Сообщение
btn-user-role = 👮‍♂️ Изменить роль
btn-user-transactions = 🧾 Транзакции
btn-user-subscription = 💳 Подписка
btn-user-role-choice = { role }
btn-user-block =  { $is_blocked ->
    [1] 🔓 Разблокировать
    *[0] 🔒 Заблокировать
    }

# Broadcast
btn-broadcast-all = 👥 Всем
btn-broadcast-user = 👤 Пользователю
btn-broadcast-subscribed = ✅ С подпиской
btn-broadcast-unsubscribed = ❌ Без подписки
btn-broadcast-expired = ⌛ Просроченным
btn-broadcast-last-message = 🕒 Последняя рассылка


# Promocodes
btn-promocodes-list = 📃 Список промокодов
btn-promocodes-search = 🔍 Поиск промокода
btn-promocodes-create = 🆕 Создать
btn-promocodes-delete = 🗑️ Удалить
btn-promocodes-edit = ✏️ Редактировать


# Maintenance
btn-maintenance-mode = { $mode ->
    [global] 🔴 Глобальный
    [purchase] 🟠 Платежи
    *[off] ⚪ Выключить
    }


# RemnaShop
btn-remnashop-admins = 👮‍♂️ Администраторы
btn-remnashop-referral = 👥 Реферальная
btn-remnashop-advertising = 🎯 Реклама
btn-remnashop-plans = 📦 Планы
btn-remnashop-notifications = 🔔 Уведомления
btn-remnashop-logs = 📄 Логи
btn-remnashop-audit = 🔍 Аудит


# Plans
btn-plans-statistics = 📊 Статистика
btn-plans-create = 🆕 Создать
btn-plan-confirm = ✅ Подтвердить
btn-plan-name = 🏷️ Имя
btn-plan-type = 🔖 Тип
btn-plan-availability = ✴️ Доступ
btn-plan-active = { $active -> 
    [1] 🟢
    *[0] 🔴
    } Статус
btn-plan-durations-prices = ⏳ Длительности | 💰 Цены
btn-plan-traffic = 🌐 Трафик
btn-plan-devices = 📱 Устройства
btn-plan-allowed = 👥 Разрешенные пользователи
btn-plan-type-choice = { $type -> 
    [traffic] 🌐 Трафик
    [devices] 📱 Устройства
    [both] 🔗 Трафик + устройства
    *[unlimited] ♾️ Безлимит
    }
btn-plan-availability-choice = { $type -> 
    [all] 🌍 Для всех
    [new] 🌱 Для новых
    [existing] 👥 Для клиентов
    [invited] ✉️ Для приглашенных
    *[allowed] 🔐 Для разрешенных
    }
btn-plan-duration = ⌛ { $duration ->
    [0] { unlimited }
    *[other] { $duration }
    } { $duration ->
    [one] день
    [few] дня
    *[other] дней
    }
btn-plan-duration-add = 🆕 Добавить длительность
btn-plan-price-choice = 💸 { $price } { $currency }


# RemnaWave
btn-remnawave-users = 👥 Пользователи
btn-remnawave-hosts = 🌐 Хосты
btn-remnawave-nodes = 🖥️ Ноды
btn-remnawave-inbounds = 🔌 Инбаунды
