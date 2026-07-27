from django.db import migrations
from django.db.models import F


def copy_batch(apps, schema_editor):
    Ticket = apps.get_model('tickets', 'Ticket')
    Ticket.objects.update(first_seen_batch=F('batch_id'), last_batch=F('batch_id'))


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0005_ticket_first_seen_batch_ticket_last_batch'),
    ]

    operations = [
        migrations.RunPython(copy_batch, noop_reverse),
    ]
