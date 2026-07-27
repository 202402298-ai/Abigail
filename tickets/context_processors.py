from .models import TeamArea


def areas_gestionadas(request):
    """Disponible en todas las plantillas: las áreas que el usuario logueado
    supervisa como 'jefe de área', para mostrarlas en el sidebar sin tener
    que pasarlas manualmente desde cada vista."""
    if not request.user.is_authenticated:
        return {}
    return {
        'sidebar_areas_gestionadas': TeamArea.objects.filter(
            jefes__user=request.user
        ).order_by('display_name')
    }
