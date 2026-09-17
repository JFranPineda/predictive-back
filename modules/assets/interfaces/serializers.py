from __future__ import annotations

from rest_framework import serializers

from modules.assets.models import Area, Equipment, MeasurementPoint


class StatusField(serializers.Serializer):
    """Catalogue text is translated server-side: the client receives the label
    already in its language, because a company adds statuses of its own."""

    def to_representation(self, instance):
        if instance is None:
            return None
        language = self.context.get("language", "es")
        return {
            "code": instance.code,
            "name": instance.translated("name", language),
            "color": instance.color,
            "kind": instance.kind,
            "measurable": instance.measurable,
            "severity": instance.severity,
        }


class AreaSerializer(serializers.ModelSerializer):
    equipment_count = serializers.IntegerField(read_only=True)
    sectors = serializers.SerializerMethodField()

    class Meta:
        model = Area
        fields = ["id", "code", "name", "parent", "criticality", "equipment_count", "sectors"]

    def get_sectors(self, obj):
        # The structure screen attaches a machine train to a sector, so it
        # needs the sectors by id rather than by name.
        return [{"id": sector.id, "name": sector.name} for sector in obj.sectors.all()]


class EquipmentSerializer(serializers.ModelSerializer):
    area = serializers.SerializerMethodField()
    asset_group = serializers.SerializerMethodField()
    condition_status = serializers.SerializerMethodField()
    availability_status = serializers.SerializerMethodField()

    class Meta:
        model = Equipment
        fields = [
            "id", "asset_code", "client_tag", "name", "equipment_type",
            "monitoring_frequency", "area", "asset_group",
            "condition_status", "availability_status", "condition_updated_at",
        ]

    def get_area(self, obj):
        area = obj.asset_group.sector.area
        return {"id": area.id, "code": area.code, "name": area.name}

    def get_asset_group(self, obj):
        return {"id": obj.asset_group_id, "name": obj.asset_group.name, "kind": obj.asset_group.kind}

    def get_condition_status(self, obj):
        return StatusField(context=self.context).to_representation(obj.condition_status)

    def get_availability_status(self, obj):
        return StatusField(context=self.context).to_representation(obj.availability_status)


class MeasurementPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeasurementPoint
        fields = ["id", "number", "axis", "side", "label", "point_type",
                  "blueprint_x", "blueprint_y"]
