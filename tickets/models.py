from django.conf import settings
from django.db import models


class TeamArea(models.Model):
    """Mapea el código de equipo (prefijo de 'Propietario') a un nombre legible
    y a si representa soporte local por país o un área funcional/corporativa.

    Editable desde /admin/ para cuando se agreguen nuevos países o áreas sin
    tener que tocar código.
    """
    TYPE_PAIS = 'pais'
    TYPE_FUNCIONAL = 'funcional'
    TYPE_CHOICES = [
        (TYPE_PAIS, 'Soporte local (país / unidad de negocio)'),
        (TYPE_FUNCIONAL, 'Área funcional / corporativa'),
    ]

    team_code = models.CharField(max_length=30, primary_key=True)
    display_name = models.CharField(max_length=100)
    area_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_FUNCIONAL)

    class Meta:
        ordering = ['area_type', 'display_name']
        verbose_name = 'Área / país de equipo'
        verbose_name_plural = 'Áreas / países de equipos'

    def __str__(self):
        return f'{self.team_code} — {self.display_name}'


class AreaManager(models.Model):
    """Vincula un usuario con la(s) área(s)/país(es) que supervisa (p. ej. el
    jefe de Honduras -> team_area=STHN). Si un usuario tiene al menos un
    registro aquí, el dashboard y el listado de tickets se filtran para
    mostrarle solo esas áreas; si no tiene ninguno, ve todo (comportamiento
    normal de un analista/consulta general).

    Un mismo usuario puede gestionar varias áreas, y una misma área puede
    tener más de un jefe asignado.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='areas_gestionadas'
    )
    team_area = models.ForeignKey(TeamArea, on_delete=models.CASCADE, related_name='jefes')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'team_area'], name='unique_user_area_manager'),
        ]
        verbose_name = 'Jefe de área'
        verbose_name_plural = 'Jefes de área'

    def __str__(self):
        return f'{self.user.username} → {self.team_area.display_name}'


class AreaFavorita(models.Model):
    """Áreas que un usuario decide 'seguir' de cerca en su propio dashboard —
    a diferencia de AreaManager, esto NO restringe qué puede ver (el usuario
    sigue viendo todo el sistema); es solo un atajo personal para filtrar
    rápido. Pensado para el equipo ITSM: son super administradores, pero le
    dan seguimiento a ciertas áreas que pueden ir cambiando con el tiempo, y
    cada quien configura las suyas.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='areas_favoritas'
    )
    team_area = models.ForeignKey(TeamArea, on_delete=models.CASCADE, related_name='favoritos')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'team_area'], name='unique_user_area_favorita'),
        ]
        ordering = ['team_area__display_name']
        verbose_name = 'Área de seguimiento'
        verbose_name_plural = 'Áreas de seguimiento'

    def __str__(self):
        return f'{self.user.username} sigue → {self.team_area.display_name}'


class ImportBatch(models.Model):
    file_name = models.CharField(max_length=255)
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    ticket_count = models.PositiveIntegerField(default=0)
    new_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    date_range_start = models.DateTimeField(null=True, blank=True)
    date_range_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-imported_at']

    def __str__(self):
        return f"{self.file_name} ({self.imported_at:%Y-%m-%d %H:%M})"


class Ticket(models.Model):
    STAGE_INGRESO = 'Ingreso'
    STAGE_NIVEL_1 = 'Nivel 1'
    STAGE_NIVEL_2 = 'Nivel 2'
    STAGE_PRE_CIERRE = 'Pre-Cierre'
    STAGE_CERRADO = 'Cerrado'
    STAGE_OTRO = 'Otro'
    STAGE_CHOICES = [
        (STAGE_INGRESO, 'Ingreso'),
        (STAGE_NIVEL_1, 'Nivel 1'),
        (STAGE_NIVEL_2, 'Nivel 2'),
        (STAGE_PRE_CIERRE, 'Pre-Cierre'),
        (STAGE_CERRADO, 'Cerrado'),
        (STAGE_OTRO, 'Otro'),
    ]

    PRIORITY_BAJA = 'Baja'
    PRIORITY_MEDIA = 'Media'
    PRIORITY_ALTA = 'Alta'
    PRIORITY_CHOICES = [
        (PRIORITY_BAJA, 'Baja'),
        (PRIORITY_MEDIA, 'Media'),
        (PRIORITY_ALTA, 'Alta'),
    ]

    STATUS_NUEVO = 'Nuevo'
    STATUS_RESPONDIDO = 'Respondido'
    STATUS_EN_PROGRESO = 'En progreso'
    STATUS_ESPERANDO_RESPUESTA = 'Esperando respuesta'
    STATUS_EN_ESPERA = 'En espera'
    STATUS_RESUELTO = 'Resuelto'
    STATUS_CHOICES = [
        (STATUS_NUEVO, 'Nuevo'),
        (STATUS_RESPONDIDO, 'Respondido'),
        (STATUS_EN_PROGRESO, 'En progreso'),
        (STATUS_ESPERANDO_RESPUESTA, 'Esperando respuesta'),
        (STATUS_EN_ESPERA, 'En espera'),
        (STATUS_RESUELTO, 'Resuelto'),
    ]

    first_seen_batch = models.ForeignKey(
        ImportBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets_nuevos'
    )
    last_batch = models.ForeignKey(
        ImportBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets_actualizados'
    )

    hesk_row_id = models.PositiveIntegerField(null=True, blank=True)
    tracking_id = models.CharField(max_length=50, unique=True)

    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)

    requester_name = models.CharField(max_length=255, blank=True)
    requester_email = models.CharField(max_length=255, blank=True)
    followers = models.CharField(max_length=500, blank=True)

    category_raw = models.CharField(max_length=255, blank=True)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default=STAGE_OTRO)
    request_type = models.CharField(max_length=50, blank=True)
    area_categoria = models.CharField(max_length=100, blank=True)

    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, blank=True)

    owner_raw = models.CharField(max_length=255, blank=True)
    team_code = models.CharField(max_length=30, blank=True, default='(sin asignar)')
    owner_name = models.CharField(max_length=255, blank=True)

    subject = models.CharField(max_length=500, blank=True)
    message = models.TextField(blank=True)

    replies_count = models.PositiveIntegerField(default=0)
    team_replies_count = models.PositiveIntegerField(default=0)
    time_spent_seconds = models.PositiveIntegerField(default=0)

    related_ticket = models.CharField(max_length=100, blank=True)
    history_raw = models.TextField(blank=True)
    ticket_url = models.URLField(max_length=500, blank=True)

    # Derivados del historial (Historial de Tiquetes), no de una columna del
    # XML: el técnico que resolvió el ticket según la regla "quién lo pasó a
    # Pre-Cierre / quién lo devolvió a ITSM por última vez", y cuánto tiempo
    # lo tuvo asignado antes de eso. Blank/None si ITSM lo resolvió directo.
    resuelto_por_team_code = models.CharField(max_length=30, blank=True)
    resuelto_por_nombre = models.CharField(max_length=255, blank=True)
    tiempo_resolucion_tecnico_segundos = models.PositiveIntegerField(null=True, blank=True)

    # Campo manual (no viene del XML de HESK): notas de seguimiento que el
    # equipo va escribiendo en el módulo "Seguimiento detallado". Se
    # preserva entre importaciones porque el ticket se identifica por
    # tracking_id, no se recrea.
    seguimiento_notas = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['team_code']),
            models.Index(fields=['created_at']),
            models.Index(fields=['last_batch']),
            models.Index(fields=['resuelto_por_team_code']),
        ]

    def __str__(self):
        return f"{self.tracking_id} - {self.subject[:40]}"

    @property
    def is_active(self):
        return self.status != self.STATUS_RESUELTO

    @property
    def is_overdue(self):
        from django.utils import timezone
        return bool(self.due_at) and self.is_active and self.due_at < timezone.now()
