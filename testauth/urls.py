# Django
# Alliance Auth
from allianceauth import urls
from django.urls import include, path

urlpatterns = [
    # Alliance Auth URLs
    path("", include(urls)),
]
