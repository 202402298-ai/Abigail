"""Genera el reporte mensual que pidió el equipo de Infraestructura (INF):
un CSV de tickets resueltos en el mes y otro de tickets pendientes con su
estado actual.

Uso:
    python manage.py reporte_infraestructura
    python manage.py reporte_infraestructura --mes 2026-08
    python manage.py reporte_infraestructura --mes 2026-08 --salida C:\ruta\reportes
"""
import csv
import datetime
import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tickets.models import Ticket
from tickets.services.history_parser import tecnicos_colaboradores

EQUIPO = 'INF'


class Command(BaseCommand):
    help = 'Genera el reporte mensual de Infraestructura (resueltos + pendientes) en CSV.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mes', default=None,
            help='Mes a reportar, formato YYYY-MM. Por defecto: mes actual.',
        )
        parser.add_argument(
            '--salida', default='.',
            help='Carpeta donde guardar los archivos CSV. Por defecto: la carpeta actual.',
        )

    def handle(self, *args, **options):
        if options['mes']:
            try:
                anio, mes = (int(p) for p in options['mes'].split('-'))
            except ValueError:
                raise CommandError('--mes debe tener el formato YYYY-MM, ej. 2026-08')
        else:
            hoy = timezone.localdate()
            anio, mes = hoy.year, hoy.month

        inicio = timezone.make_aware(datetime.datetime(anio, mes, 1))
        fin = timezone.make_aware(
            datetime.datetime(anio + 1, 1, 1) if mes == 12 else datetime.datetime(anio, mes + 1, 1)
        )

        os.makedirs(options['salida'], exist_ok=True)
        etiqueta_mes = f'{anio:04d}-{mes:02d}'

        ruta_resueltos = self._generar_resueltos(inicio, fin, etiqueta_mes, options['salida'])
        ruta_pendientes = self._generar_pendientes(etiqueta_mes, options['salida'])

        self.stdout.write(self.style.SUCCESS(f'Listo:\n  {ruta_resueltos}\n  {ruta_pendientes}'))

    def _generar_resueltos(self, inicio, fin, etiqueta_mes, carpeta):
        qs = Ticket.objects.filter(
            resuelto_por_team_code=EQUIPO,
            status=Ticket.STATUS_RESUELTO,
            resuelto_por_fecha__gte=inicio,
            resuelto_por_fecha__lt=fin,
        ).order_by('resuelto_por_fecha')

        ruta = os.path.join(carpeta, f'infraestructura_resueltos_{etiqueta_mes}.csv')
        with open(ruta, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                'ID de ticket', 'ID de seguimiento', 'Fecha de creación', 'Fecha de resolución',
                'Técnico responsable', 'Técnico(s) colaborador(es)', 'Prioridad', 'Asunto', 'Descripción',
            ])
            for t in qs:
                colaboradores = tecnicos_colaboradores(t.history_raw, EQUIPO, t.resuelto_por_nombre)
                writer.writerow([
                    t.hesk_row_id,
                    t.tracking_id,
                    t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '',
                    t.resuelto_por_fecha.strftime('%Y-%m-%d %H:%M') if t.resuelto_por_fecha else '',
                    t.resuelto_por_nombre,
                    ', '.join(colaboradores),
                    t.priority,
                    t.subject,
                    t.message,
                ])
        return ruta

    def _generar_pendientes(self, etiqueta_mes, carpeta):
        qs = (
            Ticket.objects.filter(team_code=EQUIPO)
            .exclude(status=Ticket.STATUS_RESUELTO)
            .order_by('created_at')
        )

        hoy = timezone.localdate()
        ruta = os.path.join(carpeta, f'infraestructura_pendientes_{etiqueta_mes}.csv')
        with open(ruta, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                'ID de ticket', 'ID de seguimiento', 'Fecha de creación', 'Estado',
                'Técnico asignado', 'Prioridad', 'Asunto', 'Días abierto',
            ])
            for t in qs:
                dias_abierto = (hoy - t.created_at.date()).days if t.created_at else ''
                writer.writerow([
                    t.hesk_row_id,
                    t.tracking_id,
                    t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '',
                    t.status,
                    t.owner_name,
                    t.priority,
                    t.subject,
                    dias_abierto,
                ])
        return ruta
