from django.urls import path
from . import views

app_name = 'aa_skyhook_monitor'

urlpatterns = [
    path('', views.index, name='index'),
]
