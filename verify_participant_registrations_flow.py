import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import Account
from apps.hackathons.models import Hackathon
from apps.registrations.models import Registration


def get_auth_header(user):
    token = RefreshToken.for_user(user)
    token["token_version"] = user.token_version
    return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


def main():
    print("=== STARTING PARTICIPANT REGISTRATIONS VERIFICATION ===")

    # 1. Setup real users
    user_a = Account.objects.filter(email="tutumoh@gmail.com").first()
    if not user_a:
        user_a = Account.objects.create_user(
            email="tutumoh@gmail.com",
            full_name="Participant Alpha",
            role="participant",
        )
    user_b = Account.objects.filter(email="yurafij@gmail.com").first()
    if not user_b:
        user_b = Account.objects.create_user(
            email="yurafij@gmail.com",
            full_name="Participant Beta",
            role="participant",
        )

    # 2. Setup real hackathons
    hackathon_a = Hackathon.objects.filter(slug="ethio-fin-innovate-2024").first()
    hackathon_b = Hackathon.objects.filter(slug="greenseed-challenge-2024").first()

    assert hackathon_a is not None, "Hackathon A not found"
    assert hackathon_b is not None, "Hackathon B not found"
    print(f"Hackathon A: '{hackathon_a.title}' (ID: {hackathon_a.id}, Slug: {hackathon_a.slug})")
    print(f"Hackathon B: '{hackathon_b.title}' (ID: {hackathon_b.id}, Slug: {hackathon_b.slug})")

    # Clean up any leftover test registrations for these users on these hackathons
    Registration.objects.filter(user__in=[user_a, user_b], hackathon__in=[hackathon_a, hackathon_b]).delete()

    client = APIClient()

    # 3. Test initial state for User A
    print("\n--- Testing initial empty state for User A ---")
    res = client.get("/api/v1/registrations/me", **get_auth_header(user_a))
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    body = res.json()
    assert body["data"] == [], f"Expected empty data for User A, got {body['data']}"
    print("✓ User A has 0 registrations initially.")

    # 4. User A registers for Hackathon A using SLUG
    print("\n--- User A registers for Hackathon A using slug ---")
    reg_payload_a = {
        "eligibilityConfirmed": True,
        "registrationType": "looking_for_team",
        "customAnswers": {
            "track": "FinTech",
            "personalInfo": {"city": "Addis Ababa", "role": "Software Developer"},
        },
    }
    res = client.post(
        f"/api/v1/registrations/hackathons/{hackathon_a.slug}",
        reg_payload_a,
        format="json",
        **get_auth_header(user_a),
    )
    assert res.status_code == 201, f"Registration failed: {res.status_code} - {res.content}"
    reg_a_data = res.json()
    assert reg_a_data["hackathonId"] == str(hackathon_a.id)
    assert reg_a_data["hackathonTitle"] == hackathon_a.title
    assert reg_a_data["hackathonSlug"] == hackathon_a.slug
    assert reg_a_data["registrationType"] == "looking_for_team"
    assert reg_a_data["status"] == "registered"
    print("✓ Registration response contains full hackathon relationship details.")

    # 5. Database verification
    print("\n--- Verifying registration in PostgreSQL database directly ---")
    db_reg_a = Registration.objects.filter(user=user_a, hackathon=hackathon_a).first()
    assert db_reg_a is not None, "Registration record NOT found in PostgreSQL!"
    assert db_reg_a.user_id == user_a.id, "Registration user does not match User A"
    assert db_reg_a.hackathon_id == hackathon_a.id, "Registration hackathon does not match Hackathon A"
    assert db_reg_a.registration_type == "looking_for_team"
    print(f"✓ PostgreSQL row verified: ID={db_reg_a.id}, User={db_reg_a.user.email}, Hackathon={db_reg_a.hackathon.title}")

    # 6. Duplicate registration prevention
    print("\n--- Testing duplicate registration prevention for User A on Hackathon A ---")
    res_dup = client.post(
        f"/api/v1/registrations/hackathons/{hackathon_a.id}",
        reg_payload_a,
        format="json",
        **get_auth_header(user_a),
    )
    assert res_dup.status_code == 409, f"Expected 409 Conflict, got {res_dup.status_code}: {res_dup.content}"
    print("✓ Duplicate registration correctly rejected with HTTP 409.")

    # 7. User A opens GET /api/v1/registrations/me
    print("\n--- User A requests their registrations ---")
    res_me = client.get("/api/v1/registrations/me", **get_auth_header(user_a))
    assert res_me.status_code == 200
    my_regs = res_me.json()["data"]
    assert len(my_regs) == 1
    assert my_regs[0]["hackathonId"] == str(hackathon_a.id)
    assert my_regs[0]["hackathonTitle"] == hackathon_a.title
    assert my_regs[0]["hackathonSlug"] == hackathon_a.slug
    assert my_regs[0]["hackathonLocation"] == "National Bank Innovation Lab, Addis Ababa, Ethiopia"
    assert my_regs[0]["registrationType"] == "looking_for_team"
    print("✓ Registrations page API returns Hackathon A for User A with rich details.")

    # 8. User A registers for Hackathon B using UUID
    print("\n--- User A registers for Hackathon B using UUID ---")
    reg_payload_b = {
        "eligibilityConfirmed": True,
        "registrationType": "solo",
        "customAnswers": {"track": "AgriTech"},
    }
    res_b = client.post(
        f"/api/v1/registrations/hackathons/{hackathon_b.id}",
        reg_payload_b,
        format="json",
        **get_auth_header(user_a),
    )
    assert res_b.status_code == 201, f"Registration for B failed: {res_b.status_code}"
    print("✓ User A registered for Hackathon B successfully.")

    # 9. User A requests GET /api/v1/registrations/me -> must show BOTH Hackathon A and B
    res_me_both = client.get("/api/v1/registrations/me", **get_auth_header(user_a))
    assert res_me_both.status_code == 200
    both_regs = res_me_both.json()["data"]
    assert len(both_regs) == 2, f"Expected 2 registrations for User A, found {len(both_regs)}"
    slugs = [r["hackathonSlug"] for r in both_regs]
    assert "ethio-fin-innovate-2024" in slugs and "greenseed-challenge-2024" in slugs
    print(f"✓ User A sees both registered hackathons: {slugs}")

    # 10. Multi-tenant Authorization: User B requests GET /api/v1/registrations/me
    print("\n--- Testing multi-tenant authorization (User B) ---")
    res_b_me = client.get("/api/v1/registrations/me", **get_auth_header(user_b))
    assert res_b_me.status_code == 200
    b_regs = res_b_me.json()["data"]
    assert len(b_regs) == 0, f"User B should see 0 registrations, but saw {len(b_regs)}"
    print("✓ User B sees 0 registrations. User A's registrations are NOT visible to User B.")

    # 11. User B registers for Hackathon B
    res_b_reg = client.post(
        f"/api/v1/registrations/hackathons/{hackathon_b.slug}",
        {"eligibilityConfirmed": True, "registrationType": "solo"},
        format="json",
        **get_auth_header(user_b),
    )
    assert res_b_reg.status_code == 201
    print("✓ User B registered for Hackathon B.")

    # User B now sees ONLY Hackathon B
    res_b_me2 = client.get("/api/v1/registrations/me", **get_auth_header(user_b))
    b_regs2 = res_b_me2.json()["data"]
    assert len(b_regs2) == 1
    assert b_regs2[0]["hackathonSlug"] == "greenseed-challenge-2024"
    print("✓ User B sees ONLY Hackathon B.")

    # User A STILL sees both Hackathon A and B
    res_a_check = client.get("/api/v1/registrations/me", **get_auth_header(user_a))
    assert len(res_a_check.json()["data"]) == 2
    print("✓ User A still sees both Hackathon A and Hackathon B.")

    # 12. Unauthenticated check
    print("\n--- Testing unauthenticated request rejection ---")
    res_unauth = client.get("/api/v1/registrations/me")
    assert res_unauth.status_code == 401, f"Expected 401, got {res_unauth.status_code}"
    print("✓ Unauthenticated request correctly rejected with HTTP 401.")

    print("\n=== ALL PARTICIPANT REGISTRATION CHECKS PASSED SUCCESSFULLY! ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
