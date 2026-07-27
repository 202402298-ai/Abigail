import datetime

from django import template

register = template.Library()


@register.filter
def duracion(value):
    """Formatea un timedelta (o None) como 'Xd Yh' legible."""
    if not isinstance(value, datetime.timedelta):
        return '—'
    total_seconds = value.total_seconds()
    if total_seconds < 0:
        return '—'
    dias, resto = divmod(total_seconds, 86400)
    horas, resto = divmod(resto, 3600)
    minutos = resto // 60
    dias, horas, minutos = int(dias), int(horas), int(minutos)
    if dias:
        return f'{dias}d {horas}h'
    if horas:
        return f'{horas}h {minutos}m'
    return f'{minutos}m'


@register.filter
def seconds_to_duration(value):
    if not value:
        return '0m'
    return duracion(datetime.timedelta(seconds=value))


@register.filter
def get_item(dictionary, key):
    if not dictionary:
        return None
    return dictionary.get(key)
