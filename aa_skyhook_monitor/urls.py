from django.urls import path
from . import views

app_name = 'aa_skyhook_monitor'

urlpatterns = [
    path('', views.index, name='index'),
    path('raidable/', views.raidable, name='raidable'),
    path('add-owner/', views.add_owner, name='add_owner'),
]
