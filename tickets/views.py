from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import XMLUploadForm
from .models import AreaFavorita, ImportBatch, TeamArea, Ticket
from .services import metrics
from .services.hesk_parser import HeskParseError, parse_hesk_xml
from .services.importer import importar_tickets


def _areas_gestionadas(user):
    """Áreas que el usuario supervisa como 'jefe de área'. Lista vacía si el
    usuario no tiene ninguna asignada (ve todo, como un analista/consulta)."""
    return list(
        TeamArea.objects.filter(jefes__user=user).order_by('display_name')
    )


def _tickets_visibles(user):
    """Ticket queryset que le corresponde ver a este usuario: si es jefe de
    una o más áreas, solo las suyas; si no, todo el sistema."""
    areas = _areas_gestionadas(user)
    if areas:
        codigos = [a.team_code for a in areas]
        return Ticket.objects.filter(team_code__in=codigos), areas
    return Ticket.objects.all(), areas


@login_required
def dashboard(request):
    tickets_qs, areas_gestionadas = _tickets_visibles(request.user)

    favoritas = list(TeamArea.objects.filter(favoritos__user=request.user))
    area_filtro = request.GET.get('area') or ''
    if area_filtro:
        tickets_qs = tickets_qs.filter(team_code=area_filtro)

    # Área específica que se está viendo, ya sea porque se eligió con el
    # filtro rápido de "Mis áreas" o porque el usuario es jefe de una sola
    # área: en ese caso no tiene sentido mostrar los reportes que comparan
    # entre todas las áreas.
    area_activa = area_filtro or (
        areas_gestionadas[0].team_code if len(areas_gestionadas) == 1 else ''
    )

    if not tickets_qs.exists():
        return render(request, 'tickets/dashboard.html', {
            'sin_datos': True, 'areas_gestionadas': areas_gestionadas,
            'favoritas': favoritas, 'area_filtro': area_filtro, 'area_activa': area_activa,
        })

    kpis = metrics.resumen(tickets_qs)
    por_area_pais, por_area_funcional = metrics.activos_por_area(tickets_qs)
    por_estado = metrics.tickets_por_estado(tickets_qs)
    por_prioridad = metrics.distribucion_prioridad(tickets_qs)
    buckets_tiempo_abierto, detalle_tiempo_abierto = metrics.tiempo_abierto(tickets_qs)
    _, tipo_area = metrics.tickets_por_categoria(tickets_qs)
    tiempos_global, tiempos_por_prioridad, tiempos_por_area = metrics.tiempos_de_servicio(tickets_qs)
    carga_agentes = metrics.carga_por_agente(tickets_qs)

    ranking_resolutores = metrics.resueltos_por_tecnico(area_activa) if area_activa else []

    chart_data = {
        'por_area_pais': {
            'labels': [d['display_name'] for d in por_area_pais],
            'data': [d['total'] for d in por_area_pais],
        },
        'por_area_funcional': {
            'labels': [d['display_name'] for d in por_area_funcional],
            'data': [d['total'] for d in por_area_funcional],
        },
        'por_estado': {
            'labels': [d['status'] or '(sin estado)' for d in por_estado],
            'data': [d['total'] for d in por_estado],
        },
        'por_prioridad': {
            'labels': [d['priority'] or '(sin prioridad)' for d in por_prioridad],
            'data': [d['total'] for d in por_prioridad],
        },
        'tiempo_abierto': {
            'labels': list(buckets_tiempo_abierto.keys()),
            'data': list(buckets_tiempo_abierto.values()),
        },
        'ranking_resolutores': {
            'labels': [r['nombre'] for r in ranking_resolutores],
            'data': [r['total'] for r in ranking_resolutores],
        },
    }

    context = {
        'sin_datos': False,
        'kpis': kpis,
        'por_area_pais': por_area_pais,
        'por_area_funcional': por_area_funcional,
        'por_estado': por_estado,
        'por_prioridad': por_prioridad,
        'buckets_tiempo_abierto': buckets_tiempo_abierto,
        'detalle_tiempo_abierto': detalle_tiempo_abierto[:15],
        'tipo_area': tipo_area,
        'tiempos_global': tiempos_global,
        'tiempos_por_prioridad': tiempos_por_prioridad,
        'tiempos_por_area': tiempos_por_area,
        'carga_agentes': carga_agentes[:15],
        'ranking_resolutores': ranking_resolutores,
        'chart_data': chart_data,
        'area_names': {ta.team_code: ta.display_name for ta in TeamArea.objects.all()},
        'ultima_importacion': ImportBatch.objects.first(),
        'areas_gestionadas': areas_gestionadas,
        'favoritas': favoritas,
        'area_filtro': area_filtro,
        'area_activa': area_activa,
    }
    return render(request, 'tickets/dashboard.html', context)


@login_required
def ticket_list(request):
    tickets_qs, areas_gestionadas = _tickets_visibles(request.user)
    tickets_qs = tickets_qs.select_related('last_batch')

    codes_presentes = (
        tickets_qs.values_list('team_code', flat=True).distinct().order_by('team_code')
    )
    area_lookup = {ta.team_code: ta.display_name for ta in TeamArea.objects.all()}
    team_code_options = [
        {'code': code, 'label': f"{area_lookup.get(code, code)} ({code})"}
        for code in codes_presentes
    ]

    team_code = request.GET.get('team_code')
    status = request.GET.get('status')
    priority = request.GET.get('priority')
    stage = request.GET.get('stage')
    last_batch = request.GET.get('last_batch')
    q = request.GET.get('q')

    if team_code:
        tickets_qs = tickets_qs.filter(team_code=team_code)
    if status:
        tickets_qs = tickets_qs.filter(status=status)
    if priority:
        tickets_qs = tickets_qs.filter(priority=priority)
    if stage:
        tickets_qs = tickets_qs.filter(stage=stage)
    if last_batch:
        tickets_qs = tickets_qs.filter(last_batch_id=last_batch)
    if q:
        tickets_qs = tickets_qs.filter(subject__icontains=q) | tickets_qs.filter(
            tracking_id__icontains=q
        )

    filtros = {
        'team_code_options': team_code_options,
        'statuses': Ticket.STATUS_CHOICES,
        'priorities': Ticket.PRIORITY_CHOICES,
        'stages': Ticket.STAGE_CHOICES,
        'batches': ImportBatch.objects.all()[:20],
    }

    context = {
        'tickets': tickets_qs.order_by('-created_at')[:500],
        'total_filtrado': tickets_qs.count(),
        'filtros': filtros,
        'area_names': area_lookup,
        'areas_gestionadas': areas_gestionadas,
        'selected': {
            'team_code': request.GET.get('team_code', ''),
            'status': request.GET.get('status', ''),
            'priority': request.GET.get('priority', ''),
            'stage': request.GET.get('stage', ''),
            'last_batch': request.GET.get('last_batch', ''),
            'q': request.GET.get('q', ''),
        },
    }
    return render(request, 'tickets/ticket_list.html', context)


@login_required
def mis_areas(request):
    if request.method == 'POST':
        codigos = request.POST.getlist('areas')
        AreaFavorita.objects.filter(user=request.user).delete()
        AreaFavorita.objects.bulk_create([
            AreaFavorita(user=request.user, team_area_id=codigo) for codigo in codigos
        ])
        messages.success(request, 'Tus áreas de seguimiento se actualizaron.')
        return redirect('tickets:mis_areas')

    seleccionadas = set(
        AreaFavorita.objects.filter(user=request.user).values_list('team_area_id', flat=True)
    )
    context = {
        'paises': TeamArea.objects.filter(area_type=TeamArea.TYPE_PAIS),
        'funcionales': TeamArea.objects.filter(area_type=TeamArea.TYPE_FUNCIONAL),
        'seleccionadas': seleccionadas,
    }
    return render(request, 'tickets/mis_areas.html', context)


DIAS_MINIMOS_SEGUIMIENTO = 3


@login_required
def seguimiento_detallado(request):
    if request.method == 'POST':
        actualizados = 0
        for clave, nota in request.POST.items():
            if not clave.startswith('nota_'):
                continue
            ticket_id = clave[len('nota_'):]
            actualizados += Ticket.objects.filter(pk=ticket_id).update(seguimiento_notas=nota)
        messages.success(request, 'Seguimiento guardado.')
        return redirect('tickets:seguimiento_detallado')

    tickets_qs, areas_gestionadas = _tickets_visibles(request.user)
    favoritas = list(TeamArea.objects.filter(favoritos__user=request.user))

    # Si el usuario no es jefe de área (ve todo) pero sí tiene áreas de
    # seguimiento configuradas, este módulo se enfoca solo en esas.
    if not areas_gestionadas and favoritas:
        tickets_qs = tickets_qs.filter(team_code__in=[a.team_code for a in favoritas])

    now = timezone.now()
    activos = (
        tickets_qs.exclude(status=Ticket.STATUS_RESUELTO)
        .exclude(created_at__isnull=True)
        .select_related('last_batch')
    )

    area_lookup = {ta.team_code: ta.display_name for ta in TeamArea.objects.all()}
    por_area = {}
    for t in activos:
        dias = (now - t.created_at).total_seconds() / 86400
        if dias <= DIAS_MINIMOS_SEGUIMIENTO:
            continue
        t.dias_abierto = int(dias)
        area_key = t.team_code or '(sin asignar)'
        tecnico_key = t.owner_name or '(sin asignar)'
        por_area.setdefault(area_key, {}).setdefault(tecnico_key, []).append(t)

    grupos = []
    for area_key in sorted(por_area, key=lambda c: area_lookup.get(c, c)):
        tecnicos = []
        total_area = 0
        for tecnico in sorted(por_area[area_key]):
            tickets_tecnico = sorted(por_area[area_key][tecnico], key=lambda t: t.dias_abierto, reverse=True)
            tecnicos.append({'nombre': tecnico, 'tickets': tickets_tecnico})
            total_area += len(tickets_tecnico)
        grupos.append({
            'area_code': area_key,
            'display_name': area_lookup.get(area_key, area_key),
            'tecnicos': tecnicos,
            'total': total_area,
        })

    context = {
        'grupos': grupos,
        'total_tickets': sum(g['total'] for g in grupos),
        'areas_gestionadas': areas_gestionadas,
        'favoritas': favoritas,
        'dias_minimos': DIAS_MINIMOS_SEGUIMIENTO,
    }
    return render(request, 'tickets/seguimiento_detallado.html', context)


@login_required
@permission_required('tickets.add_importbatch', raise_exception=True)
def upload_xml(request):
    if request.method == 'POST':
        form = XMLUploadForm(request.POST, request.FILES)
        if form.is_valid():
            xml_file = form.cleaned_data['xml_file']
            try:
                filas = parse_hesk_xml(xml_file)
            except HeskParseError as exc:
                messages.error(request, f'No se pudo leer el archivo: {exc}')
            else:
                if not filas:
                    messages.warning(request, 'El archivo no contiene tickets para importar.')
                else:
                    with transaction.atomic():
                        resultado = importar_tickets(filas, xml_file.name, request.user)
                    messages.success(
                        request,
                        f'Importación completa de "{xml_file.name}": '
                        f'{resultado.nuevos} tickets nuevos, {resultado.actualizados} actualizados '
                        f'y {resultado.sin_cambios} sin cambios (de {len(filas)} en el archivo).'
                    )
                    return redirect('tickets:dashboard')
    else:
        form = XMLUploadForm()

    historial = ImportBatch.objects.all()[:20]
    return render(request, 'tickets/upload.html', {'form': form, 'historial': historial})
