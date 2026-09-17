from rest_framework.routers import DefaultRouter

from modules.assets.interfaces.views import AreaViewSet, EquipmentViewSet

router = DefaultRouter()
router.register("areas", AreaViewSet, basename="area")
router.register("equipments", EquipmentViewSet, basename="equipment")

urlpatterns = router.urls
