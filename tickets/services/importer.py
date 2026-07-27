"""Lógica de importación incremental: cada ticket se identifica por su
``tracking_id`` (único en todo el sistema, no por importación). Al subir un
nuevo XML:

- Si el ticket no existía, se crea.
- Si ya existía y algún dato cambió (p. ej. pasó de "En progreso" a
  "Resuelto"), se actualiza.
- Si ya existía y nada cambió, se omite (no se reescribe en la BD).

Los tickets que estaban en la BD pero no vienen en el nuevo archivo no se
tocan: HESK puede exportar solo un subconjunto (p. ej. los tickets recientes),
así que su ausencia no significa que dejaron de existir.
"""
from dataclasses import dataclass

from ..models import ImportBatch, Ticket
from .history_parser import analizar_historial

# Campos normalizados que devuelve el parser para cada ticket, sin contar
# 'tracking_id' (que es la clave de búsqueda, no un dato a comparar/actualizar).
_CAMPOS_COMPARABLES = [
    'hesk_row_id', 'created_at', 'updated_at', 'first_response_at', 'resolved_at',
    'due_at', 'requester_name', 'requester_email', 'followers', 'category_raw',
    'stage', 'request_type', 'area_categoria', 'priority', 'status', 'owner_raw',
    'team_code', 'owner_name', 'subject', 'message', 'replies_count',
    'team_replies_count', 'time_spent_seconds', 'related_ticket', 'history_raw',
    'ticket_url',
    # Derivados del historial (ver history_parser.analizar_historial). Se
    # recalculan en cada importación porque el historial puede crecer con
    # eventos nuevos entre una exportación y la siguiente.
    'resuelto_por_team_code', 'resuelto_por_nombre', 'tiempo_resolucion_tecnico_segundos',
]


@dataclass
class ResultadoImportacion:
    batch: ImportBatch
    nuevos: int
    actualizados: int
    sin_cambios: int


def importar_tickets(filas, file_name, user) -> ResultadoImportacion:
    """Crea el ImportBatch y aplica upsert de los tickets. Debe llamarse
    dentro de una transacción atómica."""
    fechas_creacion = [f['created_at'] for f in filas if f['created_at']]
    batch = ImportBatch.objects.create(
        file_name=file_name,
        imported_by=user,
        ticket_count=len(filas),
        date_range_start=min(fechas_creacion) if fechas_creacion else None,
        date_range_end=max(fechas_creacion) if fechas_creacion else None,
    )

    tracking_ids = [fila['tracking_id'] for fila in filas]
    existentes = {
        t.tracking_id: t for t in Ticket.objects.filter(tracking_id__in=tracking_ids)
    }

    nuevos_objs = []
    cambiados_objs = []
    nuevos = actualizados = sin_cambios = 0

    for fila in filas:
        tracking_id = fila['tracking_id']
        existente = existentes.get(tracking_id)

        (
            fila['resuelto_por_team_code'],
            fila['resuelto_por_nombre'],
            fila['tiempo_resolucion_tecnico_segundos'],
        ) = analizar_historial(fila['history_raw'])
        # Los CharField no aceptan None (deben quedar como '' si no aplica).
        fila['resuelto_por_team_code'] = fila['resuelto_por_team_code'] or ''
        fila['resuelto_por_nombre'] = fila['resuelto_por_nombre'] or ''

        if existente is None:
            datos = {k: v for k, v in fila.items() if k != 'tracking_id'}
            nuevos_objs.append(Ticket(
                tracking_id=tracking_id,
                first_seen_batch=batch,
                last_batch=batch,
                **datos,
            ))
            nuevos += 1
            continue

        cambio = False
        for campo in _CAMPOS_COMPARABLES:
            nuevo_valor = fila[campo]
            if getattr(existente, campo) != nuevo_valor:
                setattr(existente, campo, nuevo_valor)
                cambio = True

        if cambio:
            existente.last_batch = batch
            cambiados_objs.append(existente)
            actualizados += 1
        else:
            sin_cambios += 1

    if nuevos_objs:
        Ticket.objects.bulk_create(nuevos_objs)
    if cambiados_objs:
        Ticket.objects.bulk_update(cambiados_objs, fields=_CAMPOS_COMPARABLES + ['last_batch'])

    batch.new_count = nuevos
    batch.updated_count = actualizados
    batch.unchanged_count = sin_cambios
    batch.save(update_fields=['new_count', 'updated_count', 'unchanged_count'])

    return ResultadoImportacion(batch=batch, nuevos=nuevos, actualizados=actualizados, sin_cambios=sin_cambios)
