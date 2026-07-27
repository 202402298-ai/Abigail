"""Funciones de agregación para el dashboard. Todas reciben un queryset de
``Ticket`` ya filtrado (por batch, rango de fechas, etc.) desde la vista."""
import datetime

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
from django.db.models.functions import TruncDate
from django.utils import timezone

from tickets.models import TeamArea, Ticket


def resumen(tickets_qs):
    now = timezone.now()
    hoy_inicio = now.replace(hour=0, minute=0, second=0, microsecond=0)
    activos_qs = tickets_qs.exclude(status=Ticket.STATUS_RESUELTO)
    return {
        'total_tickets': tickets_qs.count(),
        'total_activos': activos_qs.count(),
        'total_vencidos': activos_qs.filter(due_at__lt=now).count(),
        'resueltos_hoy': tickets_qs.filter(resolved_at__gte=hoy_inicio).count(),
    }


def _team_area_lookup():
    return {ta.team_code: ta for ta in TeamArea.objects.all()}


# Códigos que se excluyen del bucket "funcional/corporativa" del dashboard:
# ITSM solo coordina/valida (no resuelve) y "(sin asignar)" no es un área real,
# así que no aportan a la comparación de carga entre áreas funcionales.
_EXCLUIDOS_DE_FUNCIONAL = {'ITSM', '(sin asignar)'}


def activos_por_area(tickets_qs):
    """Devuelve (paises, funcionales) — tickets activos agrupados por equipo,
    separando soporte local (país/unidad de negocio, resuelve el ticket) de
    áreas funcionales/corporativas como Desarrollo, Infraestructura,
    Inteligencia de Negocio, etc. (ITSM y "sin asignar" se excluyen de este
    último grupo: ITSM coordina/valida pero no resuelve)."""
    raw = list(
        tickets_qs.exclude(status=Ticket.STATUS_RESUELTO)
        .values('team_code')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    lookup = _team_area_lookup()
    paises, funcionales = [], []
    for row in raw:
        team_code = row['team_code'] or '(sin asignar)'
        ta = lookup.get(team_code)
        if ta:
            row['display_name'] = ta.display_name
            area_type = ta.area_type
        else:
            # Código nuevo, aún no registrado en TeamArea: se asume país si
            # sigue el patrón "ST<código>" (igual que los ya conocidos:
            # STHN, STSV, STCR...), si no, se trata como funcional.
            row['display_name'] = team_code
            area_type = TeamArea.TYPE_PAIS if team_code.startswith('ST') else TeamArea.TYPE_FUNCIONAL
        row['area_type'] = area_type
        if area_type == TeamArea.TYPE_PAIS:
            paises.append(row)
        elif team_code not in _EXCLUIDOS_DE_FUNCIONAL:
            funcionales.append(row)
    return paises, funcionales


def tickets_por_estado(tickets_qs):
    return list(
        tickets_qs.values('status').annotate(total=Count('id')).order_by('-total')
    )


def distribucion_prioridad(tickets_qs):
    return list(
        tickets_qs.values('priority').annotate(total=Count('id')).order_by('-total')
    )


TIEMPO_ABIERTO_BUCKETS = ['0-1 día', '1-3 días', '3-7 días', '+7 días']


def tiempo_abierto(tickets_qs):
    """Devuelve (buckets, detalle) para tickets activos, según hace cuánto se crearon."""
    activos = tickets_qs.exclude(status=Ticket.STATUS_RESUELTO).exclude(created_at__isnull=True)
    now = timezone.now()
    buckets = {b: 0 for b in TIEMPO_ABIERTO_BUCKETS}
    detalle = []
    for t in activos.order_by('created_at'):
        dias = (now - t.created_at).total_seconds() / 86400
        if dias <= 1:
            buckets['0-1 día'] += 1
        elif dias <= 3:
            buckets['1-3 días'] += 1
        elif dias <= 7:
            buckets['3-7 días'] += 1
        else:
            buckets['+7 días'] += 1
        detalle.append({'ticket': t, 'dias_abierto': round(dias, 1)})
    detalle.sort(key=lambda d: d['dias_abierto'], reverse=True)
    return buckets, detalle


def tickets_por_categoria(tickets_qs):
    """Devuelve (por_etapa, tipo_x_area) — tipo_x_area solo cubre tickets en Nivel 2,
    que es la única etapa donde HESK trae esa clasificación adicional."""
    por_etapa = list(
        tickets_qs.values('stage').annotate(total=Count('id')).order_by('-total')
    )
    tipo_area = list(
        tickets_qs.filter(stage=Ticket.STAGE_NIVEL_2)
        .values('request_type', 'area_categoria')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    return por_etapa, tipo_area


def tiempos_de_servicio(tickets_qs):
    """Promedios de tiempo de primera respuesta y de resolución, global y desglosado."""
    resp_expr = ExpressionWrapper(
        F('first_response_at') - F('created_at'), output_field=DurationField()
    )
    res_expr = ExpressionWrapper(
        F('resolved_at') - F('created_at'), output_field=DurationField()
    )
    base = tickets_qs.annotate(tiempo_primera_respuesta=resp_expr, tiempo_resolucion=res_expr)

    global_avg = base.aggregate(
        avg_respuesta=Avg('tiempo_primera_respuesta'),
        avg_resolucion=Avg('tiempo_resolucion'),
    )
    resueltos = base.exclude(tiempo_resolucion__isnull=True)
    por_prioridad = list(
        resueltos.values('priority')
        .annotate(avg_resolucion=Avg('tiempo_resolucion'), total=Count('id'))
        .order_by('priority')
    )
    por_area = list(
        resueltos.values('team_code')
        .annotate(avg_resolucion=Avg('tiempo_resolucion'), total=Count('id'))
        .order_by('-total')
    )
    lookup = _team_area_lookup()
    for row in por_area:
        team_code = row['team_code'] or '(sin asignar)'
        ta = lookup.get(team_code)
        row['display_name'] = ta.display_name if ta else team_code
    return global_avg, por_prioridad, por_area


def alertas_vencimiento(tickets_qs, proximas_horas=48):
    """Devuelve (vencidos, proximos_a_vencer) — tickets activos con fecha de vencimiento."""
    now = timezone.now()
    activos_con_vencimiento = tickets_qs.exclude(status=Ticket.STATUS_RESUELTO).exclude(
        due_at__isnull=True
    )
    vencidos = activos_con_vencimiento.filter(due_at__lt=now).order_by('due_at')
    limite = now + datetime.timedelta(hours=proximas_horas)
    proximos = activos_con_vencimiento.filter(due_at__gte=now, due_at__lte=limite).order_by(
        'due_at'
    )
    return vencidos, proximos


def carga_por_agente(tickets_qs):
    rows = list(
        tickets_qs.exclude(status=Ticket.STATUS_RESUELTO)
        .exclude(owner_name='')
        .values('owner_name', 'team_code')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    lookup = _team_area_lookup()
    for row in rows:
        team_code = row['team_code'] or '(sin asignar)'
        ta = lookup.get(team_code)
        row['display_name'] = ta.display_name if ta else team_code
    return rows


def tendencia_temporal(tickets_qs):
    """Devuelve (creados_por_dia, resueltos_por_dia) para graficar la evolución del backlog."""
    creados = list(
        tickets_qs.exclude(created_at__isnull=True)
        .annotate(dia=TruncDate('created_at'))
        .values('dia')
        .annotate(total=Count('id'))
        .order_by('dia')
    )
    resueltos = list(
        tickets_qs.exclude(resolved_at__isnull=True)
        .annotate(dia=TruncDate('resolved_at'))
        .values('dia')
        .annotate(total=Count('id'))
        .order_by('dia')
    )
    return creados, resueltos


def resueltos_por_tecnico(area_team_code):
    """Ranking de técnicos que más han resuelto tickets en un área específica
    (según el análisis del historial, no el Propietario final del ticket —
    ver services/history_parser.py) y su tiempo promedio de resolución
    (el tiempo que tuvieron el ticket asignado, no el ciclo de vida completo).

    Usa el área tal como quedó registrada en el momento en que se resolvió
    cada ticket, por eso consulta directamente sobre todos los tickets
    (Ticket.objects) en vez del queryset ya filtrado por área actual del
    dashboard: el Propietario final casi siempre queda en ITSM, así que
    filtrar por team_code actual excluiría lo que resolvieron los técnicos.
    """
    resueltos = (
        Ticket.objects.filter(resuelto_por_team_code=area_team_code)
        .exclude(resuelto_por_nombre='')
        .values('resuelto_por_nombre')
        .annotate(
            total=Count('id'),
            avg_segundos=Avg('tiempo_resolucion_tecnico_segundos'),
        )
        .order_by('-total')
    )
    filas = []
    for row in resueltos:
        avg_segundos = row['avg_segundos']
        filas.append({
            'nombre': row['resuelto_por_nombre'],
            'total': row['total'],
            'avg_duracion': (
                datetime.timedelta(seconds=avg_segundos) if avg_segundos is not None else None
            ),
        })
    return filas
