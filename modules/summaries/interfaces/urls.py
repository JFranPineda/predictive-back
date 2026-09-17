from django.urls import path

from modules.summaries.interfaces.views import PlantSummaryView

urlpatterns = [path("summaries/plant/", PlantSummaryView.as_view(), name="plant-summary")]
