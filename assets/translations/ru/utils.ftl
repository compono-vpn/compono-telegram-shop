# Test
btn = Кнопка
msg = Сообщение
unlimited = ∞
development = В разработке

# Commands
cmd-start = Перезапустить бота
cmd-help = Помощь

# Used to create a blank line between elements
space = {" "}
separator = {"\u00A0"}


# Roles
role-dev = Разработчик
role-admin = Администратор
role-user = Пользователь

role = 
    { $role ->
    [dev] { role-dev }
    [admin] { role-admin }
    *[user] { role-user }
}


# Units
unit-byte = Б
unit-kilobyte = КБ
unit-megabyte = МБ
unit-gigabyte = ГБ
unit-terabyte = ТБ

unit-second = { $value } { $value ->
    [one] секунда
    [few] секунды
    *[other] секунд
}

unit-minute = { $value } { $value ->
    [one] минута
    [few] минуты
    *[other] минут
}

unit-hour = { $value } { $value ->
    [one] час
    [few] часа
    *[other] часов
}

unit-day = { $value } { $value ->
    [one] день
    [few] дня
    *[other] дней
}

unit-month = { $value } { $value ->
    [one] месяц
    [few] месяца
    *[other] месяцев
}

unit-year = { $value } { $value ->
    [one] год
    [few] года
    *[other] лет
}


# Gateways
gateway-type = { $type ->
    [telegram_stars] Звезды
    [yookassa] ЮKassa
    [yoomoney] ЮMoney
    [cryptomus] Cryptomus
    [heleket] Heleket
    *[other] { $type }
}