from django.contrib import admin

from .models import AreaFavorita, AreaManager, ImportBatch, TeamArea, Ticket


@admin.register(TeamArea)
class TeamAreaAdmin(admin.ModelAdmin):
    list_display = ('team_code', 'display_name', 'area_type')
    list_editable = ('display_name', 'area_type')
    list_filter = ('area_type',)


@admin.register(AreaManager)
class AreaManagerAdmin(admin.ModelAdmin):
    list_display = ('user', 'team_area')
    list_filter = ('team_area',)
    autocomplete_fields = ('user',)
    search_fields = ('user__username', 'team_area__display_name', 'team_area__team_code')


@admin.register(AreaFavorita)
class AreaFavoritaAdmin(admin.ModelAdmin):
    list_display = ('user', 'team_area')
    list_filter = ('team_area',)
    autocomplete_fields = ('user',)
    search_fields = ('user__username', 'team_area__display_name', 'team_area__team_code')


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        'file_name', 'imported_at', 'imported_by', 'ticket_count',
        'new_count', 'updated_count', 'unchanged_count',
        'date_range_start', 'date_range_end',
    )
    ordering = ('-imported_at',)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('tracking_id', 'last_batch', 'subject', 'status', 'priority', 'team_code', 'stage', 'created_at')
    list_filter = ('last_batch', 'status', 'priority', 'stage', 'team_code')
    search_fields = ('tracking_id', 'subject', 'requester_name', 'requester_email')
