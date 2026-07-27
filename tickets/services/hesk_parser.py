"""Parser para el XML (SpreadsheetML) que exporta la plataforma de tickets HESK.

El archivo NO es XML "una etiqueta por campo": es el formato Excel XML
(Workbook > Worksheet > Table > Row > Cell > Data), con el namespace
``urn:schemas-microsoft-com:office:spreadsheet``. Este módulo lee la fila de
encabezado para mapear nombre de columna -> índice, de modo que el parser
sobrevive a que HESK reordene o agregue columnas entre exportaciones.
"""
import datetime
import xml.etree.ElementTree as ET

from django.utils import timezone

from tickets.models import Ticket

SS_NS = 'urn:schemas-microsoft-com:office:spreadsheet'
NS = {'ss': SS_NS}

_STAGE_MAP = {
    'Ingreso': Ticket.STAGE_INGRESO,
    'Nivel 1': Ticket.STAGE_NIVEL_1,
    'Nivel 2': Ticket.STAGE_NIVEL_2,
    'Pre-Cierre': Ticket.STAGE_PRE_CIERRE,
    'Cerrado': Ticket.STAGE_CERRADO,
}


class HeskParseError(ValueError):
    """Se lanza cuando el archivo no tiene la forma esperada de export HESK."""


def _cell_ns_tag(tag):
    return f'{{{SS_NS}}}{tag}'


def _row_values(row_elem, num_columns):
    """Convierte una fila <Row> en una lista de textos alineada por columna.

    SpreadsheetML puede omitir celdas vacías al final de la fila y usar el
    atributo ss:Index para indicar en qué columna retoma la siguiente celda
    con datos, así que no basta con leer las celdas en orden secuencial.
    """
    values = [''] * num_columns
    next_index = 1
    for cell in row_elem.findall('ss:Cell', NS):
        index_attr = cell.get(_cell_ns_tag('Index'))
        if index_attr:
            next_index = int(index_attr)
        col = next_index - 1
        if col >= num_columns:
            break
        data = cell.find('ss:Data', NS)
        values[col] = (data.text or '') if data is not None else ''
        next_index += 1
    return values


def read_rows(file_obj):
    """Lee el archivo y devuelve (encabezados, filas_de_datos_como_listas_de_texto)."""
    tree = ET.parse(file_obj)
    root = tree.getroot()

    worksheet = root.find('ss:Worksheet', NS)
    if worksheet is None:
        raise HeskParseError('No se encontró la hoja (Worksheet) esperada en el XML.')
    table = worksheet.find('ss:Table', NS)
    if table is None:
        raise HeskParseError('No se encontró la tabla (Table) esperada en el XML.')

    rows = table.findall('ss:Row', NS)
    if not rows:
        raise HeskParseError('El archivo no contiene filas de datos.')

    header_row = rows[0]
    num_columns = len(header_row.findall('ss:Cell', NS))
    headers = [h.strip() for h in _row_values(header_row, num_columns)]

    data_rows = [_row_values(row, num_columns) for row in rows[1:]]
    return headers, data_rows


def _parse_datetime(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _parse_int(value, default=0):
    value = (value or '').strip()
    if not value:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def _parse_time_spent_seconds(value):
    value = (value or '').strip()
    if not value:
        return 0
    parts = value.split(':')
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts[-3:]
    return hours * 3600 + minutes * 60 + seconds


def _split_category(category_raw):
    """'ITSM Nivel 2 | Incidencia | Infraestructura' -> (stage, tipo, area)."""
    segments = [s.strip() for s in category_raw.split('|')]
    first = segments[0]
    stage_name = first
    if stage_name.startswith('ITSM '):
        stage_name = stage_name[len('ITSM '):].strip()
    stage = _STAGE_MAP.get(stage_name, Ticket.STAGE_OTRO)
    request_type = segments[1] if len(segments) > 1 else ''
    area_categoria = segments[2] if len(segments) > 2 else ''
    return stage, request_type, area_categoria


def _split_owner(owner_raw):
    """'STHN - Alejandro Aguilar' -> ('STHN', 'Alejandro Aguilar')."""
    owner_raw = (owner_raw or '').strip()
    if not owner_raw:
        return '(sin asignar)', ''
    if ' - ' in owner_raw:
        team_code, owner_name = owner_raw.split(' - ', 1)
        return team_code.strip(), owner_name.strip()
    return owner_raw, ''


REQUIRED_HEADERS = ['ID de seguimiento', 'Fecha', 'Estado', 'Categoría', 'Propietario']


def parse_hesk_xml(file_obj):
    """Parsea el export de HESK y devuelve una lista de dicts normalizados,
    uno por ticket, listos para construir instancias de ``Ticket`` (sin
    ``batch``, que se asigna en la vista de importación)."""
    headers, data_rows = read_rows(file_obj)
    idx = {h: i for i, h in enumerate(headers)}

    missing = [h for h in REQUIRED_HEADERS if h not in idx]
    if missing:
        raise HeskParseError(
            'El XML no tiene las columnas esperadas de un export de HESK. '
            f'Faltan: {", ".join(missing)}'
        )

    def get(vals, name, default=''):
        i = idx.get(name)
        if i is None or i >= len(vals):
            return default
        return vals[i]

    tickets = []
    for vals in data_rows:
        tracking_id = get(vals, 'ID de seguimiento').strip()
        if not tracking_id:
            continue

        category_raw = get(vals, 'Categoría').strip()
        stage, request_type, area_categoria = _split_category(category_raw)

        owner_raw = get(vals, 'Propietario').strip()
        team_code, owner_name = _split_owner(owner_raw)

        tickets.append({
            'hesk_row_id': _parse_int(get(vals, '#'), default=None),
            'tracking_id': tracking_id,
            'created_at': _parse_datetime(get(vals, 'Fecha')),
            'updated_at': _parse_datetime(get(vals, 'Actualizado')),
            'first_response_at': _parse_datetime(get(vals, 'Primera respuesta en')),
            'resolved_at': _parse_datetime(get(vals, 'Resuelto en')),
            'due_at': _parse_datetime(get(vals, 'Fecha de vencimiento')),
            'requester_name': get(vals, 'Nombre').strip(),
            'requester_email': get(vals, 'E-mail').strip(),
            'followers': get(vals, 'Seguidores').strip(),
            'category_raw': category_raw,
            'stage': stage,
            'request_type': request_type,
            'area_categoria': area_categoria,
            'priority': get(vals, 'Prioridad').strip(),
            'status': get(vals, 'Estado').strip(),
            'owner_raw': owner_raw,
            'team_code': team_code,
            'owner_name': owner_name,
            'subject': get(vals, 'Asunto').strip(),
            'message': get(vals, 'Mensaje'),
            'replies_count': _parse_int(get(vals, 'Respuestas')),
            'team_replies_count': _parse_int(get(vals, 'Respuestas (Equipo)')),
            'time_spent_seconds': _parse_time_spent_seconds(get(vals, 'Tiempo Dedicado')),
            'related_ticket': get(vals, 'Relación de Requerimiento').strip(),
            'history_raw': get(vals, 'Historial de Tiquetes'),
            'ticket_url': get(vals, 'URL de tiquete').strip(),
        })

    return tickets
