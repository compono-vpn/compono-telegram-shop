# Test
btn = Кнопка
msg = Сообщение
unlimited = ∞

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
unit-bytes = Б
unit-kilobytes = КБ
unit-megabytes = МБ
unit-gigabytes = ГБ
unit-terabytes = ТБ

unit-seconds = { $value ->
    [one] секунда
    [few] секунды
    *[other] секунд
}

unit-minutes = { $value ->
    [one] минута
    [few] минуты
    *[other] минут
}

unit-hours = { $value ->
    [one] час
    [few] часа
    *[other] часов
}

unit-days = { $value ->
    [one] день
    [few] дня
    *[other] дней
}