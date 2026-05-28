from django.urls import path, include
from rest_framework.routers import DefaultRouter
from api.views import (
    PlantLookupViewSet, AirportLookupViewSet, EmissionFactorViewSet,
    IngestionBatchViewSet, NormalizedRecordViewSet, StatsViewSet, SimulationViewSet
)

router = DefaultRouter()
router.register(r'plants', PlantLookupViewSet, basename='plant')
router.register(r'airports', AirportLookupViewSet, basename='airport')
router.register(r'factors', EmissionFactorViewSet, basename='factor')
router.register(r'batches', IngestionBatchViewSet, basename='batch')
router.register(r'records', NormalizedRecordViewSet, basename='record')

# Stats ViewSet doesn't use standard model query, so we construct custom path
# and same for simulation triggers
urlpatterns = [
    path('', include(router.urls)),
    path('stats/', StatsViewSet.as_view({'get': 'list'}), name='stats'),
    path('simulation/seed_all/', SimulationViewSet.as_view({'post': 'seed_simulation_data'}), name='seed-simulation'),
]
