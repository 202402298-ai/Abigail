"""Analiza el 'Historial de Tiquetes' de HESK (texto libre en <li>) para
determinar qué técnico resolvió realmente el ticket y cuánto tiempo lo tuvo
asignado, ya que el campo Propietario final casi siempre queda en ITSM
(porque ITSM hace el pre-cierre y cierre), no en el técnico que lo trabajó.

Regla (confirmada contra datos reales antes de implementarla):
1. El resolutor es quien movió el ticket a la etapa "Pre-Cierre" por última
   vez (si pasó por ahí más de una vez, se usa la más reciente).
2. Si el ticket nunca pasó por Pre-Cierre, se usa como respaldo quien lo
   devolvió a ITSM por última vez (último "asignado a ITSM ... por X").
3. Si no ocurrió ninguno de los dos, ITSM resolvió el ticket directamente
   sin involucrar a nadie más — no hay un técnico que atribuir.

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
_ACTOR_RE = re.compile(r'^(?P<team>\S+)\s*-\s*(?P<name>.+?)\s*\([^)]*\)\s*$')


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
    """Devuelve (team_code, nombre, segundos_asignado) del técnico que
    resolvió el ticket según su historial, o (None, None, None) si no hay
    ninguno que atribuir (ITSM lo resolvió directamente)."""
    eventos = _parse_eventos(history_raw)
    if not eventos:
        return None, None, None

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
        return None, None, None

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

    return resolver['team'], resolver['name'], segundos
