from __future__ import annotations

from dataclasses import asdict

from rest_framework import serializers

from modules.core.domain.manifest import ModuleInfo


class ModuleInfoSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    version = serializers.CharField()
    summary = serializers.CharField()
    category = serializers.CharField()
    depends = serializers.ListField(child=serializers.CharField())
    is_core = serializers.BooleanField()
    state = serializers.CharField()
    installed_version = serializers.CharField(allow_null=True)
    upgradable = serializers.BooleanField()
    missing_depends = serializers.ListField(child=serializers.CharField())
    menu = serializers.ListField(child=serializers.DictField())
    permissions = serializers.ListField(child=serializers.ListField(child=serializers.CharField()))

    @staticmethod
    def from_info(info: ModuleInfo) -> dict:
        m = info.manifest
        return {
            "code": m.code,
            "name": m.name,
            "version": m.version,
            "summary": m.summary,
            "category": m.category,
            "depends": list(m.depends),
            "is_core": m.is_core,
            "state": info.state,
            "installed_version": info.installed_version,
            "upgradable": info.upgradable,
            "missing_depends": list(info.missing_depends),
            "menu": [asdict(item) for item in m.menu],
            "permissions": [list(p) for p in m.permissions],
        }
