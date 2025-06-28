msg-plan-details =
    <blockquote>
    { $type ->
    [devices]
    • Количество устройств: { $current_devices } / { $max_devices }
    • Заканчивается через: { $expiry_time }
    *[traffic]
    • Трафик: { $current_traffic } / { $max_traffic }
    • Заканчивается через: { $expiry_time }
    }
    </blockquote>

# Menu
msg-menu-subscription =
    <b>💳 Подписка:</b>
    { $status ->
    [active]
    { $plan }
    [expired]
    <blockquote>
    • Срок действия истёк.
    • Чтобы продлить перейдите в меню «💳 Подписка»
    </blockquote>
    *[none]
    <blockquote>
    • У вас нет подписки

    Для оформления перейдите в меню «💳 Подписка»
    </blockquote>
    }

msg-menu-profile =
    <b>👤 Профиль:</b>
    <blockquote>
    • ID: <code>{ $id }</code>
    • Имя: { $name }
    </blockquote>


# Dashboard
msg-dashboard-main = <b>🛠 Панель управления</b>
msg-statistics-main = <b>📊 Статистика</b>
msg-users-main = <b>👥 Пользователи</b>
msg-broadcast-main = <b>📢 Рассылка</b>
msg-promocodes-main = <b>🎟 Промокоды</b>
msg-maintenance-main =
    <b>🚧 Режим обслуживания</b>
    
    Статус: { $status ->
    [global] 🔴 Включен (глобальный)
    [purchase] 🟠 Включен (платежи)
    *[off] ⚪ Выключен
    }

# Users
msg-users-search =
    <b>🔍 Поиск пользователя</b>

    Введите ID пользователя или перешлите любое его сообщение

msg-user-main = 
    <b>📝 Информация о пользователе</b>

    👤 Профиль:
    <blockquote>
    • ID: <code>{ $id }</code>
    • Имя: { $name }
    • Роль: { role }
    </blockquote>

    💳 Подписка:
    { $has_subscription ->
    [1]
    { $plan }
    *[0]
    <blockquote>
    • Нет оформленной подписки
    </blockquote>
    }

msg-user-role = 
    <b>👮‍♂️ Изменить роль</b>
    
    Выберите новую роль для пользователя


msg-users-blacklist =
    <b>🚫 Черный список</b>

    Заблокировано: { $count_blocked } / { $count_users } ({ $percent }%)

msg-users-unblock-all =
    <b>🚫 Черный список</b>

    Вы уверены, что хотите разблокировать всех пользователей?


# RemnaWave
msg-remnawave-main =
    <b>🌊 RemnaWave</b>
    
    🖥️ Система:
    <blockquote>
    • ЦПУ: { $cpu_cores } { $cpu_cores ->
    [one] ядро
    [few] ядра
    *[other] ядер
    } { $cpu_threads } { $cpu_threads ->
    [one] поток
    [few] потока
    *[other] потоков
    }
    • ОЗУ: { $ram_used } / { $ram_total } ({ $ram_used_percent }%)
    • Аптайм: { $uptime }
    </blockquote>

msg-remnawave-users =
    <b>👥 Пользователи</b>

    📊 Статистика:
    <blockquote>
    • Всего: { $users_total }
    • Активные: { $users_active }
    • Отключённые: { $users_disabled }
    • Ограниченные: { $users_limited }
    • Истёкшие: { $users_expired }
    </blockquote>

    🟢 Онлайн:
    <blockquote>
    • За день: { $online_last_day }
    • За неделю: { $online_last_week }
    • Никогда не заходили: { $online_never }
    • Сейчас онлайн: { $online_now }
    </blockquote>

msg-remnawave-host-details =
    { $remark } ({ $status ->
    [on] включен
    *[off] выключен
    }):
    <blockquote>
    • Адрес: <code>{ $address }:{ $port }</code>
    • Инбаунд: <code>{ $inbound_uuid }</code>
    </blockquote>

msg-remnawave-hosts =
    <b>🌐 Хосты</b>
    
    { $hosts }

msg-remnawave-node-details =
    { $country } { $name } ({ $status ->
    [on] подключено
    *[off] отключено
    }):
    <blockquote>
    • Адрес: <code>{ $address }:{ $port }</code>
    • Аптайм (xray): { $xray_uptime }
    • Пользователей онлайн: { $users_online }
    • Трафик: { $traffic_used } / {$traffic_limit}
    </blockquote>

msg-remnawave-nodes =
    <b>🖥️ Ноды</b>

    { $nodes }

msg-remnawave-inbound-details =
    🔗 { $tag }
    <blockquote>
    • UUID: <code>{ $uuid }</code>
    • Протокол: { $type } ({ $network })
    • Порт: { $port }
    • Безопасность: { $security } 
    </blockquote>

msg-remnawave-inbounds =
    <b>🔌 Инбаунды</b>

    { $inbounds }


# RemnaShop
msg-remnashop-main = <b>🛍 RemnaShop</b>
msg-remnashop-admins = <b>👮‍♂️ Администраторы</b>


# Plans
msg-plans-main = <b>📦 Планы</b>
msg-plan-config =
    <b>📦 Конфигурация плана</b>

    <blockquote>
    Имя: { $name }
    Тип: { $type -> 
        [traffic] Трафик
        [devices] Устройства
        [both] Трафик + устройства
        *[unlimited] Безлимитный
        }
    Доступ: { $availability -> 
        [all] Для всех
        [new] Для новых
        [existing] Для существующих
        [invited] Для приглашенных
        *[allowed] Для разрешенных
        }
    Статус: { $active -> 
        [1] 🟢 Включен
        *[0] 🔴 Выключен
        }
    </blockquote>
    
    <blockquote>
    Трафик: { $has_traffic_limit -> 
        [1] { $traffic_limit } ГБ
        *[0] безлимит
        }
    Устройства: { $has_device_limit -> 
        [1] { $device_limit } { $device_limit ->
            [one] устройство
            [few] устройства
            *[other] устройств
            }
        *[0] безлимит
        }
    </blockquote>

    <blockquote>
    Длительности: { $durations }
    Цены: { $prices }
    </blockquote>

    Выберите пункт для изменения

msg-plan-name =
    <b>🏷️ Изменить имя</b>

    Введите новое название плана

msg-plan-type =
    <b>🔖 Изменить тип</b>

    Выберите новый тип плана

msg-plan-availability =
    <b>✴️ Изменить доступность</b>

    Выберите доступность плана

msg-plan-traffic =
    <b>🌐 Изменить лимит трафика</b>

    Введите новый лимит трафика плана

msg-plan-devices =
    <b>📱 Изменить лимит устройств</b>

    Введите новый лимит устройств плана

msg-plan-durations =
    <b>⏳ Длительности плана</b>

    Выберите длительность для настройки цены

msg-plan-duration =
    <b>⏳ Добавить длительность плана</b>

    Введите новую длительность в днях

msg-plan-prices =
    <b>💰 Изменить цены длительности ({ $duration ->
            [0] { unlimited }
            *[other] { $duration }
        } { $duration ->
            [one] день
            [few] дня
            *[other] дней
    })</b>

    Выберите валюту с ценой для изменения

msg-plan-price =
    <b>💰 Изменить цену для длительности ({ $duration ->
            [0] { unlimited }
            *[other] { $duration }
        } { $duration ->
            [one] день
            [few] дня
            *[other] дней
    })</b>

    Введите новую цену для валюты { $currency }