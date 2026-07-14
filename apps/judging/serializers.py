"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.
"""

from rest_framework import serializers

# class ExampleSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = None
#         fields = "__all__"
