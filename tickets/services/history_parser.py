"""Analiza el 'Historial de Tiquetes' de HESK (texto libre en <li>) para
determinar qué técnico resolvió realmente el ticket y cuánto tiempo lo tuvo
asignado, ya que el campo Propietario final casi siempre queda en ITSM
(porque ITSM hace el pre-cierre y cierre), no en el técnico que lo trabajó.

Regla (confirmada contra datos reales antes de implementarla):
1. El resolutor es quien movió el ticket a la etapa "Pre-Cierre" por última
   vez (si pasó por ahí más de una vez, se usa la más reciente).
2. Si el ticket nunca pasó por Pre-Cierre, se usa como respaldo quien lo
   devolvió a ITSM por última vez (último "asignado a ITSM ... por X").
3. Si no ocurrió ninguno de los dos, es porque ITSM resolvió el ticket
   directamente sin involucrar a otra área — en ese caso (y SOLO en ese
   caso, es decir, solo para atribuir resoluciones al área ITSM) se usa
   como respaldo quien lo cerró ("cerrado por X" o "movido a la categoría
   ... Cerrado por X"). Esta regla 3 no aplica a las demás áreas: ahí el
   resolutor siempre sale de las reglas 1 o 2.

El "tiempo de resolución del técnico" es la diferencia entre el momento en
que se le asignó el ticket por última vez (antes de resolverlo) y el
momento en que lo resolvió — no el tiempo de vida completo del ticket.
"""
import datetime
import re

_LI_RE = re.compile(
    r'<li class="smaller">(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (?P<text>.*?)</li>',
    re.DOTALL,
)
_ASIGNADO_RE = re.compile(r'^asignado a (?P<target>.+?) por (?P<actor>.+)$')
_CATEGORIA_RE = re.compile(r'^movido a la categor[ií]a (?P<categoria>.+?) por (?P<actor>.+)$')
_CERRADO_RE = re.compile(r'^cerrado por (?P<actor>.+)$')
_ACTOR_RE = re.compile(r'^(?P<team>\S+)\s*-\s*(?P<name>.+?)\s*\([^)]*\)\s*$')
# Cualquier evento del historial termina en "... por EQUIPO - Nombre (usuario)",
# sea cual sea la acción (asignación, cambio de categoría, de estado, cierre,
# etc.) — sirve para reportes de actividad diaria que no distinguen el tipo
# de acción, solo que la persona haya tocado el ticket ese día.
_EVENTO_CON_ACTOR_RE = re.compile(r'.* por (?P<actor>\S+\s*-\s*.+?\s*\([^)]*\))\s*$')


def _split_actor(texto):
    """'ITSM - Fernando Salgado (fsalgado)' -> ('ITSM', 'Fernando Salgado')."""
    m = _ACTOR_RE.match(texto.strip())
    if not m:
        return None, None
    return m.group('team').strip(), m.group('name').strip()


def _parse_eventos(history_raw):
    eventos = []
    for m in _LI_RE.finditer(history_raw or ''):
        try:
            ts = datetime.datetime.strptime(m.group('ts'), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        eventos.append({'ts': ts, 'texto': m.group('text').strip()})
    return eventos


def analizar_historial(history_raw):
    """Devuelve (team_code, nombre, segundos_asignado, fecha_resolucion) del
    técnico que resolvió el ticket según su historial, o (None, None, None,
    None) si no hay absolutamente ningún evento de asignación, cierre o
    resolución que atribuir a nadie.

    ``fecha_resolucion`` es el momento exacto del evento (naive, en hora
    local) — se usa para filtrar reportes por rango de fechas en vez del
    campo "Resuelto en" del XML, que HESK deja vacío en la gran mayoría de
    los tickets aunque sí estén resueltos."""
    eventos = _parse_eventos(history_raw)
    if not eventos:
        return None, None, None, None

    resolver = None
    for e in eventos:
        m = _CATEGORIA_RE.match(e['texto'])
        if m and 'pre-cierre' in m.group('categoria').lower():
            team, name = _split_actor(m.group('actor'))
            if team and name:
                resolver = {'ts': e['ts'], 'team': team, 'name': name}

    if resolver is None:
        for e in eventos:
            m = _ASIGNADO_RE.match(e['texto'])
            if not m:
                continue
            target_team, _ = _split_actor(m.group('target'))
            if target_team != 'ITSM':
                continue
            actor_team, actor_name = _split_actor(m.group('actor'))
            if actor_team and actor_name:
                resolver = {'ts': e['ts'], 'team': actor_team, 'name': actor_name}

    if resolver is None:
        # Respaldo exclusivo para ITSM: si nadie pasó el ticket por
        # Pre-Cierre ni se lo devolvió a ITSM (porque ITSM lo resolvió
        # directamente, sin involucrar a otra área), se atribuye a quien lo
        # cerró — pero solo si esa persona es de ITSM. Para las demás áreas
        # esta regla no aplica: si no hay Pre-Cierre ni devolución, no se
        # atribuye a nadie (ver reglas 1 y 2 arriba).
        for e in eventos:
            actor_texto = None
            m_cerrado = _CERRADO_RE.match(e['texto'])
            if m_cerrado:
                actor_texto = m_cerrado.group('actor')
            else:
                m_cat = _CATEGORIA_RE.match(e['texto'])
                if m_cat and 'cerrado' in m_cat.group('categoria').lower():
                    actor_texto = m_cat.group('actor')
            if actor_texto is None:
                continue
            actor_team, actor_name = _split_actor(actor_texto)
            if actor_team == 'ITSM' and actor_name:
                resolver = {'ts': e['ts'], 'team': actor_team, 'name': actor_name}

    if resolver is None:
        return None, None, None, None

    inicio_ts = None
    for e in eventos:
        if e['ts'] > resolver['ts']:
            break
        m = _ASIGNADO_RE.match(e['texto'])
        if not m:
            continue
        target_team, target_name = _split_actor(m.group('target'))
        if target_team == resolver['team'] and target_name == resolver['name']:
            inicio_ts = e['ts']

    segundos = None
    if inicio_ts is not None:
        segundos = max(0, int((resolver['ts'] - inicio_ts).total_seconds()))

    return resolver['team'], resolver['name'], segundos, resolver['ts']


def eventos_de_actividad(history_raw):
    """Devuelve una lista de (fecha, team_code, nombre) — uno por cada
    evento del historial que tenga un actor identificable, sin importar el
    tipo de acción (asignación, cambio de categoría, de estado, cierre...).
    Para reportes de "actividad diaria": qué tickets tocó cada quien y
    cuándo, independientemente de si eso resolvió el ticket o no."""
    resultado = []
    for e in _parse_eventos(history_raw):
        m = _EVENTO_CON_ACTOR_RE.match(e['texto'])
        if not m:
            continue
        team, nombre = _split_actor(m.group('actor'))
        if team and nombre:
            resultado.append((e['ts'].date(), team, nombre))
    return resultado
