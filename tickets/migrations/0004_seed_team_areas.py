from django.db import migrations

# Mapeo inicial de código de equipo -> nombre legible y tipo, según lo
# observado en el export de HESK y lo confirmado por el usuario:
# - Los equipos "ST<país>" son soporte técnico local (resuelven el ticket).
# - STPC es una excepción al patrón geográfico: es "Soporte Local Proconsumo"
#   (unidad de negocio, no un país) — igual se agrupa como soporte local
#   porque funcionalmente resuelve tickets de la misma forma.
# - ITSM es la mesa de servicio/coordinación: valida y enruta el ticket al
#   técnico correcto y hace el pre-cierre con el usuario, pero no resuelve.
# - DSL = Desarrollo, INF = Infraestructura, ITN = Inteligencia de Negocio,
#   TDG = Transformación Digital: áreas funcionales/corporativas.
SEED = [
    ('STHN', 'Honduras', 'pais'),
    ('STSV', 'El Salvador', 'pais'),
    ('STCR', 'Costa Rica', 'pais'),
    ('STGT', 'Guatemala', 'pais'),
    ('STNI', 'Nicaragua', 'pais'),
    ('STPN', 'Panamá', 'pais'),
    ('STMX', 'México', 'pais'),
    ('STRD', 'República Dominicana', 'pais'),
    ('STPC', 'Proconsumo', 'pais'),
    ('ITSM', 'ITSM (Mesa de servicio / coordinación)', 'funcional'),
    ('DSL', 'Desarrollo', 'funcional'),
    ('INF', 'Infraestructura', 'funcional'),
    ('ITN', 'Inteligencia de Negocio', 'funcional'),
    ('TDG', 'Transformación Digital', 'funcional'),
    ('(sin asignar)', '(Sin asignar)', 'funcional'),
]


def seed_team_areas(apps, schema_editor):
    TeamArea = apps.get_model('tickets', 'TeamArea')
    for team_code, display_name, area_type in SEED:
        TeamArea.objects.update_or_create(
            team_code=team_code,
            defaults={'display_name': display_name, 'area_type': area_type},
        )


def remove_team_areas(apps, schema_editor):
    TeamArea = apps.get_model('tickets', 'TeamArea')
    TeamArea.objects.filter(team_code__in=[code for code, _, _ in SEED]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0003_alter_teamarea_area_type'),
    ]

    operations = [
        migrations.RunPython(seed_team_areas, remove_team_areas),
    ]
