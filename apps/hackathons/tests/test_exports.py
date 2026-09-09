"""
Unit tests for Hackathon export generation engine and services.
"""

import pytest
from rest_framework.exceptions import NotFound, PermissionDenied
from apps.hackathons import services
from apps.hackathons.tests.factories import PublishedHackathonFactory
from apps.organizations.tests.factories import VerifiedOrganizationFactory
from apps.accounts.models import RoleAssignment


@pytest.mark.django_db
class TestHackathonExports:
    def test_export_complete_excel(self, organizer_account, verified_org, organizer_role):
        hackathon = PublishedHackathonFactory(
            host_org=verified_org,
            title="AI Innovation Hackathon",
            slug="ai-innovation-hackathon",
            total_prize_budget="50000.00",
            prize_distribution={"firstPlaceAmount": "25000.00", "currency": "ETB"},
            field="Artificial Intelligence",
            location_name="Addis Ababa, Ethiopia",
            open_to=["ALL"],
            tags=["AI", "Machine Learning"],
        )

        result = services.export_hackathon_data(
            actor=organizer_account,
            hackathon_id=str(hackathon.id),
            resource="complete",
            format="xlsx",
        )

        assert result["filename"] == "ai-innovation-hackathon-Final-Report.xlsx"
        assert result["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert result["is_binary"] is True
        assert len(result["content"]) > 0

    def test_export_participants_csv(self, organizer_account, verified_org, organizer_role):
        hackathon = PublishedHackathonFactory(
            host_org=verified_org,
            title="FinTech Sprint",
            slug="fintech-sprint",
        )

        result = services.export_hackathon_data(
            actor=organizer_account,
            hackathon_id=str(hackathon.id),
            resource="participants",
            format="csv",
        )

        assert result["filename"] == "fintech-sprint-Participants.csv"
        assert result["content_type"] == "text/csv; charset=utf-8"
        assert result["is_binary"] is False
        assert "Participant Name" in result["content"]

    def test_export_pdf_report(self, organizer_account, verified_org, organizer_role):
        hackathon = PublishedHackathonFactory(
            host_org=verified_org,
            title="AgriTech Challenge",
            slug="agritech-challenge",
        )

        result = services.export_hackathon_data(
            actor=organizer_account,
            hackathon_id=str(hackathon.id),
            resource="analytics",
            format="pdf",
        )

        assert result["filename"] == "agritech-challenge-Analytics-Report.pdf"
        assert result["content_type"] == "application/pdf"
        assert result["is_binary"] is True
        assert len(result["content"]) > 0

    def test_export_all_managed_hackathons(self, organizer_account, verified_org, organizer_role):
        h1 = PublishedHackathonFactory(host_org=verified_org, title="Hackathon One")
        h2 = PublishedHackathonFactory(host_org=verified_org, title="Hackathon Two")

        result = services.export_hackathon_data(
            actor=organizer_account,
            hackathon_id="all",
            resource="complete",
            format="xlsx",
        )

        assert result["filename"] == "all-managed-hackathons-Final-Report.xlsx"
        assert len(result["content"]) > 0

    def test_export_permission_denied_for_other_org(self, organizer_account, other_account):
        other_org = VerifiedOrganizationFactory()
        hackathon = PublishedHackathonFactory(host_org=other_org, title="Secret Hackathon")

        # other_account is not an organizer of other_org
        with pytest.raises(PermissionDenied):
            services.export_hackathon_data(
                actor=other_account,
                hackathon_id=str(hackathon.id),
                resource="complete",
                format="xlsx",
            )


    def test_export_not_found(self, organizer_account):
        import uuid
        with pytest.raises(NotFound):
            services.export_hackathon_data(
                actor=organizer_account,
                hackathon_id=str(uuid.uuid4()),
                resource="complete",
                format="xlsx",
            )
