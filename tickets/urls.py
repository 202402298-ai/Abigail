from django.urls import path

from . import views

app_name = 'tickets'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('tickets/', views.ticket_list, name='ticket_list'),
    path('mis-areas/', views.mis_areas, name='mis_areas'),
    path('seguimiento/', views.seguimiento_detallado, name='seguimiento_detallado'),
    path('subir/', views.upload_xml, name='upload'),
]
