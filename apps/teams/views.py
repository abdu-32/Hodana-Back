"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from rest_framework import viewsets, permissions

# class ExampleViewSet(viewsets.ModelViewSet):
#     permission_classes = [permissions.IsAuthenticated]
