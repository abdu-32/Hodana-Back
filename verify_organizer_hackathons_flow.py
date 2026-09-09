import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import Account, RoleAssignment
from apps.organizations.models import Organization
from apps.hackathons.models import Hackathon

def get_auth_header(user):
    token = RefreshToken.for_user(user)
    token["token_version"] = user.token_version
    return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

def main():
    print("=== STARTING ORGANIZER HACKATHONS VERIFICATION ===")

    # 1. Setup organizer user
    organizer = Account.objects.filter(email="abdusemir47@gmail.com").first()
    if not organizer:
        organizer = Account.objects.create_user(
            email="abdusemir47@gmail.com",
            full_name="Abdu Semir Organizer",
            role="organizer",
        )

    client = APIClient()
    auth_header = get_auth_header(organizer)

    # 2. Check initial managed hackathons
    res = client.get("/api/v1/hackathons/?managed=true", **auth_header)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    initial_count = res.json()["meta"]["total"]
    print(f"✓ Initial managed hackathons for {organizer.email}: {initial_count}")

    # 3. Create a new hackathon without passing host_org_id (simulating the web UI)
    create_payload = {
        "title": "Fintech Innovation Cup 2026",
        "description": "Building next gen payments in Ethiopia",
        "registrationOpensAt": "2026-09-01T00:00:00Z",
        "registrationClosesAt": "2026-10-15T00:00:00Z",
        "submissionOpensAt": "2026-09-10T00:00:00Z",
        "submissionClosesAt": "2026-10-25T00:00:00Z",
        "totalPrizeBudget": "50000.00",
        "locationMode": "in_person",
        "locationName": "Addis Ababa, Ethiopia",
        "field": "Technology",
        "openTo": ["ALL"],
        "eligibilityRules": {"openToAll": True},
        "tags": ["Fintech", "Banking"],
    }

    create_res = client.post("/api/v1/hackathons/", create_payload, format="json", **auth_header)
    assert create_res.status_code == 201, f"Expected 201, got {create_res.status_code}: {create_res.json()}"
    created_hackathon = create_res.json()
    hackathon_id = created_hackathon["id"]
    print(f"✓ Hackathon created in DB: ID={hackathon_id}, Title='{created_hackathon['title']}'")

    # 4. Organizer publishes the hackathon
    publish_res = client.put(f"/api/v1/hackathons/{hackathon_id}", {"status": "published"}, format="json", **auth_header)
    assert publish_res.status_code == 200, f"Expected 200, got {publish_res.status_code}: {publish_res.json()}"
    assert publish_res.json()["status"] == "published"
    print("✓ Hackathon successfully published in DB.")

    # 5. Organizer refreshes their dashboard / hackathons list (GET /hackathons/?managed=true)
    refresh_res = client.get("/api/v1/hackathons/?managed=true", **auth_header)
    assert refresh_res.status_code == 200, f"Expected 200, got {refresh_res.status_code}"
    managed_list = refresh_res.json()["data"]
    found = any(h["id"] == hackathon_id for h in managed_list)
    assert found, f"Created hackathon {hackathon_id} was NOT found on refresh in managed list!"
    print(f"✓ Hackathon verified on page refresh! Found in managed list of {len(managed_list)} items.")

    # 6. Verify in PostgreSQL directly
    db_hackathon = Hackathon.objects.filter(id=hackathon_id).first()
    assert db_hackathon is not None, "Hackathon not found in DB directly!"
    assert db_hackathon.status == "published", f"Expected published, got {db_hackathon.status}"
    assert db_hackathon.created_by == organizer, "Created_by does not match organizer!"
    print(f"✓ Verified directly in PostgreSQL: ID={db_hackathon.id}, status={db_hackathon.status}, host_org={db_hackathon.host_org.name}")

    print("\n=== ALL ORGANIZER HACKATHON CREATION & PERSISTENCE CHECKS PASSED! ===")

if __name__ == "__main__":
    main()
