import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import RoleAssignment
from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import HackathonFactory
from apps.organizations.tests.factories import OrganizationFactory
from apps.registrations.models import Registration
from apps.registrations.tests.factories import RegistrationFactory, WithdrawnRegistrationFactory


@pytest.mark.django_db
class TestOrganizerRegistrations:
    def test_unauthenticated_request_rejected(self):
        client = APIClient()
        response = client.get("/api/v1/registrations/organizer")
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_organizer_only_sees_own_hackathon_registrations(self):
        client = APIClient()

        # Organizer A & Org A
        org_a = OrganizationFactory()
        organizer_a = AccountFactory()
        RoleAssignment.objects.create(
            user=organizer_a, role="organizer", scope_type="organization", scope_id=org_a.id
        )
        hackathon_a1 = HackathonFactory(host_org=org_a, created_by=organizer_a, title="AI Innovation")
        hackathon_a2 = HackathonFactory(host_org=org_a, created_by=organizer_a, title="Web3 Sprint")

        # Organizer B & Org B
        org_b = OrganizationFactory()
        organizer_b = AccountFactory()
        RoleAssignment.objects.create(
            user=organizer_b, role="organizer", scope_type="organization", scope_id=org_b.id
        )
        hackathon_b1 = HackathonFactory(host_org=org_b, created_by=organizer_b, title="HealthTech Challenge")

        # Registrations
        p1 = AccountFactory(full_name="Dawit Abebe", email="dawit@aau.edu.et", university="Addis Ababa University")
        p2 = AccountFactory(full_name="Selamawit Bekele", email="selam@astu.edu.et", university="ASTU")
        p3 = AccountFactory(full_name="Ermias Tesfaye", email="ermias@mit.edu", university="MIT")

        reg_a1 = RegistrationFactory(hackathon=hackathon_a1, user=p1)
        reg_a2 = RegistrationFactory(hackathon=hackathon_a2, user=p2)
        reg_b1 = RegistrationFactory(hackathon=hackathon_b1, user=p3)

        # Log in as Organizer A
        client.force_authenticate(user=organizer_a)
        response = client.get("/api/v1/registrations/organizer")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        reg_ids = [r["id"] for r in data]
        assert str(reg_a1.id) in reg_ids
        assert str(reg_a2.id) in reg_ids
        assert str(reg_b1.id) not in reg_ids

        # Meta stats
        meta = response.json()["meta"]
        assert meta["total"] == 2
        assert meta["stats"]["totalRegistrations"] == 2
        assert meta["stats"]["uniqueParticipants"] == 2

    def test_organizer_cannot_access_other_organizers_hackathon(self):
        client = APIClient()

        org_a = OrganizationFactory()
        organizer_a = AccountFactory()
        RoleAssignment.objects.create(
            user=organizer_a, role="organizer", scope_type="organization", scope_id=org_a.id
        )

        org_b = OrganizationFactory()
        organizer_b = AccountFactory()
        RoleAssignment.objects.create(
            user=organizer_b, role="organizer", scope_type="organization", scope_id=org_b.id
        )
        hackathon_b = HackathonFactory(host_org=org_b, created_by=organizer_b)
        RegistrationFactory(hackathon=hackathon_b)

        # Organizer A tries to access registrations for Hackathon B
        client.force_authenticate(user=organizer_a)
        response = client.get(f"/api/v1/registrations/organizer?hackathonId={hackathon_b.id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_specific_hackathon_filter(self):
        client = APIClient()

        org_a = OrganizationFactory()
        organizer_a = AccountFactory()
        RoleAssignment.objects.create(
            user=organizer_a, role="organizer", scope_type="organization", scope_id=org_a.id
        )
        h1 = HackathonFactory(host_org=org_a, created_by=organizer_a)
        h2 = HackathonFactory(host_org=org_a, created_by=organizer_a)

        r1 = RegistrationFactory(hackathon=h1)
        r2 = RegistrationFactory(hackathon=h2)

        client.force_authenticate(user=organizer_a)
        response = client.get(f"/api/v1/registrations/organizer?hackathonId={h1.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == str(r1.id)

    def test_search_and_status_filtering(self):
        client = APIClient()

        org = OrganizationFactory()
        organizer = AccountFactory()
        RoleAssignment.objects.create(
            user=organizer, role="organizer", scope_type="organization", scope_id=org.id
        )
        h = HackathonFactory(host_org=org, created_by=organizer)

        p1 = AccountFactory(full_name="Kassahun Kebede", email="kassahun@tech.et", city="Addis Ababa")
        p2 = AccountFactory(full_name="Tigist Haile", email="tigist@design.et", city="Hawassa")

        r1 = RegistrationFactory(hackathon=h, user=p1)
        r2 = WithdrawnRegistrationFactory(hackathon=h, user=p2)

        client.force_authenticate(user=organizer)

        # Search by name
        res = client.get("/api/v1/registrations/organizer?search=Kassahun")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["data"]) == 1
        assert res.json()["data"][0]["id"] == str(r1.id)

        # Filter by status withdrawn
        res_withdrawn = client.get("/api/v1/registrations/organizer?status=withdrawn")
        assert res_withdrawn.status_code == status.HTTP_200_OK
        assert len(res_withdrawn.json()["data"]) == 1
        assert res_withdrawn.json()["data"][0]["id"] == str(r2.id)
