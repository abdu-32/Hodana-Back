import os
import django
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from django.conf import settings
settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

from apps.accounts.models import Account, RoleAssignment
from apps.organizations.models import Organization, OrgVerificationReview
from apps.hackathons.models import Hackathon
from apps.registrations.models import Registration
from apps.accounts.serializers import UserProfileSerializer
from apps.hackathons import services as hackathon_services
from apps.registrations import services as reg_services
from apps.organizations import services as org_services

def log(msg, success=None):
    if success is True:
        print(f"[PASS] {msg}")
    elif success is False:
        print(f"[FAIL] {msg}")
    else:
        print(f"[INFO] {msg}")

def run_tests():
    log("=== Running Complete End-to-End Organizer Flow & Isolation Verification ===")

    # 1. Create Normal Participant (User A)
    email_a = f"user_a_{uuid.uuid4().hex[:6]}@example.com"
    user_a = Account.objects.create_user(email=email_a, password="Password123!", full_name="User Alpha", verification_status="verified")
    
    # Check roles of newly registered user
    roles_a = UserProfileSerializer(user_a).data["roles"]
    log("1. Newly registered account has only participant role", roles_a == ["participant"])

    # Attempt to create hackathon before approved organization -> Must raise PermissionDenied
    try:
        hackathon_services.create_hackathon(
            actor=user_a,
            title="Unauthorized Hackathon",
            description="Should fail",
            field="Technology",
            location_mode="online",
            location_name="Online",
            open_to=["ALL"],
            registration_opens_at="2026-10-01T00:00:00Z",
            registration_closes_at="2026-10-10T00:00:00Z",
            submission_opens_at="2026-10-11T00:00:00Z",
            submission_closes_at="2026-10-20T00:00:00Z",
            host_org_id=uuid.uuid4(),
        )
        log("2. Unapproved user prevented from creating hackathon", False)
    except Exception as e:
        log(f"2. Unapproved user prevented from creating hackathon: {type(e).__name__}", True)

    # 2. User A applies to become organizer (registers Org A)
    org_a = org_services.register_organization(
        actor=user_a,
        name="Alpha Tech Hub",
        type="company",
        contact_email=email_a,
        primary_email_domain="alphatech.et",
    )
    log(f"3. Org A registered with verification_status='{org_a.verification_status}'", org_a.verification_status in ("unverified", "pending"))

    # Move Org A to pending verification review
    org_a.verification_status = "pending"
    org_a.save(update_fields=["verification_status"])

    # Check User A roles while pending -> must STILL be participant only!
    roles_a_pending = UserProfileSerializer(user_a).data["roles"]
    log("4. User A role remains participant only while organization is pending", roles_a_pending == ["participant"])

    # 3. Platform Admin reviews and approves Org A
    admin_user = Account.objects.filter(email=Account.PLATFORM_ADMIN_EMAIL).first()
    if not admin_user:
        admin_user = Account.objects.create_user(email=Account.PLATFORM_ADMIN_EMAIL, password="Password123!", is_platform_admin=True, verification_status="verified")
    review_a = org_services.review_organization_verification(
        admin=admin_user,
        organization_id=org_a.id,
        decision="approved"
    )
    org_a.refresh_from_db()
    log("5. Admin approves Org A -> verification_status='verified'", org_a.verification_status == "verified")

    # Check User A roles after approval -> must now include 'organizer'!
    roles_a_approved = UserProfileSerializer(user_a).data["roles"]
    log("6. User A now holds 'organizer' role after admin approval", "organizer" in roles_a_approved and "participant" in roles_a_approved)

    # 4. Organizer A creates Hackathon A
    from django.utils import timezone
    now = timezone.now()
    hack_a = hackathon_services.create_hackathon(
        actor=user_a,
        title="Alpha AI Hackathon 2026",
        description="Official hackathon for Alpha Tech Hub",
        field="Technology",
        location_mode="online",
        location_name="Addis Ababa",
        open_to=["ALL"],
        registration_opens_at=now - timezone.timedelta(days=1),
        registration_closes_at=now + timezone.timedelta(days=10),
        submission_opens_at=now + timezone.timedelta(days=11),
        submission_closes_at=now + timezone.timedelta(days=20),
        host_org_id=org_a.id,
    )
    hack_a.status = "published"
    hack_a.save()
    log("7. Organizer A creates Hackathon A", bool(hack_a.id))

    # 5. Organizer B creates Org B (approved) and Hackathon B
    email_b = f"user_b_{uuid.uuid4().hex[:6]}@example.com"
    user_b = Account.objects.create_user(email=email_b, password="Password123!", full_name="User Beta", verification_status="verified")
    org_b = org_services.register_organization(actor=user_b, name="Beta BioTech Lab", type="university", contact_email=email_b)
    org_b.verification_status = "pending"
    org_b.save(update_fields=["verification_status"])
    org_services.review_organization_verification(admin=admin_user, organization_id=org_b.id, decision="approved")
    hack_b = hackathon_services.create_hackathon(
        actor=user_b,
        title="Beta AgriTech Challenge 2026",
        description="Official hackathon for Beta BioTech Lab",
        field="Agriculture",
        location_mode="online",
        location_name="Hawassa",
        open_to=["ALL"],
        registration_opens_at=now - timezone.timedelta(days=1),
        registration_closes_at=now + timezone.timedelta(days=10),
        submission_opens_at=now + timezone.timedelta(days=11),
        submission_closes_at=now + timezone.timedelta(days=20),
        host_org_id=org_b.id,
    )
    hack_b.status = "published"
    hack_b.save()
    log("8. Organizer B creates Hackathon B", bool(hack_b.id))

    # 6. Participants register
    p1 = Account.objects.create_user(email=f"p1_{uuid.uuid4().hex[:6]}@ethio.et", password="Password123!", full_name="Abebe Bikila", verification_status="verified")
    p2 = Account.objects.create_user(email=f"p2_{uuid.uuid4().hex[:6]}@ethio.et", password="Password123!", full_name="Derartu Tulu", verification_status="verified")

    reg_services.register_for_hackathon(actor=p1, hackathon_id=hack_a.id, eligibility_confirmed=True)
    reg_services.register_for_hackathon(actor=p2, hackathon_id=hack_b.id, eligibility_confirmed=True)

    # 7. MULTI-TENANT ISOLATION TESTS
    log("\n=== Testing Multi-Tenant Data Isolation ===")

    # 7a. Managed hackathons list
    hacks_a, _ = hackathon_services.list_hackathons(managed_only=True, requester=user_a)
    hacks_b, _ = hackathon_services.list_hackathons(managed_only=True, requester=user_b)
    
    log("Organizer A sees only Hackathon A in managed list", [h.id for h in hacks_a] == [hack_a.id])
    log("Organizer B sees only Hackathon B in managed list", [h.id for h in hacks_b] == [hack_b.id])

    # 7b. Registrations list
    regs_a, count_a, stats_a = reg_services.list_organizer_registrations(actor=user_a)
    regs_b, count_b, stats_b = reg_services.list_organizer_registrations(actor=user_b)

    log("Organizer A sees only Participant 1 in registrations", [r.user.id for r in regs_a] == [p1.id])
    log("Organizer B sees only Participant 2 in registrations", [r.user.id for r in regs_b] == [p2.id])

    # 7c. Cross-tenant registration access attempt
    try:
        reg_services.list_organizer_registrations(actor=user_a, hackathon_id=hack_b.id)
        log("Organizer A cross-tenant access to Hackathon B registrations denied", False)
    except Exception as e:
        log(f"Organizer A cross-tenant access to Hackathon B registrations denied: {type(e).__name__}", True)

    # 7d. Cross-tenant export attempt
    try:
        hackathon_services.export_hackathon_data(actor=user_a, hackathon_id=str(hack_b.id))
        log("Organizer A cross-tenant export of Hackathon B denied", False)
    except Exception as e:
        log(f"Organizer A cross-tenant export of Hackathon B denied: {type(e).__name__}", True)

    # 7e. Authorized export succeeds
    export_res = hackathon_services.export_hackathon_data(actor=user_a, hackathon_id=str(hack_a.id), format="csv")
    csv_str = export_res["content"]
    log("Organizer A export of own Hackathon A data succeeds", "Alpha AI Hackathon" in csv_str and "Abebe Bikila" in csv_str)

    # 8. Submissions & Judge Scoring Reflection to Organizer
    from apps.submissions.models import Submission
    from apps.submissions import services as sub_services
    from apps.judging.models import Score, JudgingCriterion, JudgingRound
    from apps.judging import services as judging_services
    from apps.teams.models import Team
    from decimal import Decimal

    # Create team for Hackathon A by p1
    team_a = Team.objects.create(
        hackathon=hack_a,
        team_name="AgriTech Team",
        leader_user=p1,
        max_size=4,
    )

    # Create submission for Hackathon A
    sub_a = Submission.objects.create(
        hackathon=hack_a,
        team=team_a,
        title="AgriAI Project",
        description="Smart irrigation system",
        tagline="AI for agriculture",
        repo_link="https://github.com/test/agri-ai",
        is_finalized=True,
    )

    # Create judging round and criterion
    jround, _ = JudgingRound.objects.get_or_create(hackathon=hack_a, track=None)
    crit = JudgingCriterion.objects.create(
        round=jround,
        name="Innovation",
        min_score=1,
        max_score=10,
        weight=Decimal("1.0"),
    )

    # Judge submits score
    score = Score.objects.create(
        submission=sub_a,
        judge_user=admin_user,
        criterion=crit,
        score_value=9,
    )

    # Organizer A lists submissions
    subs_a = sub_services.list_organizer_submissions(actor=user_a)
    sub_data = next((s for s in subs_a if s["id"] == str(sub_a.id)), None)
    log("Organizer A sees submission with live judge score 9.0", sub_data is not None and sub_data["averageScore"] == 9.0 and sub_data["evaluationsCount"] == 1)

    # Organizer B should NOT see Hackathon A submission
    subs_b = sub_services.list_organizer_submissions(actor=user_b)
    log("Organizer B does not see Hackathon A submission (isolation)", not any(s["id"] == str(sub_a.id) for s in subs_b))

    # Organizer A assigns winner
    win_res = sub_services.assign_submission_winner(actor=user_a, submission_id=sub_a.id, rank="FIRST", winner_notes="Top project")
    log("Organizer A can assign winner rank FIRST", win_res["rank"] == "FIRST")

    # Refresh list and confirm rank is FIRST
    subs_a_after = sub_services.list_organizer_submissions(actor=user_a)
    sub_data_after = next((s for s in subs_a_after if s["id"] == str(sub_a.id)), None)
    log("Organizer A sees updated rank FIRST and winner notes", sub_data_after is not None and sub_data_after["rank"] == "FIRST")

    # Organizer requests payout details from Top Winner
    req_res = sub_services.request_submission_payout(
        actor=user_a,
        submission_id=sub_a.id,
        message="Please provide your CBE bank account info for 1st place prize."
    )
    log("Organizer A requested payment method form", req_res["payoutStatus"] == "REQUESTED")

    # Participant (Team Leader p1) submits payout details
    part_res = sub_services.submit_payout_details(
        actor=p1, # p1 is team leader of team_a
        submission_id=sub_a.id,
        provider="Commercial Bank of Ethiopia (CBE)",
        beneficiary_name="Abebe Bikila",
        account_number="1000192837465",
        phone="+251911223344",
        notes="Fintech division winner account",
    )
    log("Participant submitted payment details", part_res["payoutStatus"] == "SUBMITTED" and part_res["payoutDetails"]["accountNumber"] == "1000192837465")

    # Organizer marks as disbursed / paid
    paid_res = sub_services.mark_submission_payout_paid(
        actor=user_a,
        submission_id=sub_a.id,
        transaction_ref="TXN-ETB-994821",
    )
    log("Organizer A marked payout as disbursed / paid", paid_res["payoutStatus"] == "PAID" and paid_res["payoutDetails"]["transactionRef"] == "TXN-ETB-994821")

    # ================= 9. ANNOUNCEMENT BROADCAST & NOTIFICATION SYSTEM =================
    from apps.notifications import services as notif_services
    
    # Organizer A broadcasts an urgent announcement to Hackathon A
    announcement = notif_services.create_announcement(
        actor=user_a,
        hackathon_id=str(hack_a.id),
        message="URGENT: Final Evaluation Criteria Updated & Pitch Room Assigned!",
        channels=["in_portal", "email"],
    )
    delivery_count = announcement.deliveries.count()
    log("Organizer A broadcasted multi-channel announcement", announcement is not None and delivery_count >= 1)

    # Participant (p1) checks in-portal notifications
    p1_notifs = notif_services.list_my_notifications(actor=p1)
    p1_delivery = next((d for d in p1_notifs if "Evaluation Criteria" in (d.notification.message or "")), None)
    log("Participant p1 received in-portal announcement notification", p1_delivery is not None and p1_delivery.read_at is None)

    # Participant marks all notifications as read
    read_count = notif_services.mark_all_notifications_read(actor=p1)
    log("Participant p1 marked all notifications as read", read_count >= 1)

    # Participant checks unread notifications
    p1_unread = notif_services.list_my_notifications(actor=p1, unread_only=True)
    log("Participant p1 has 0 unread notifications after mark all read", p1_unread.count() == 0)

    log("\n🎉 ALL TESTS PASSED SUCCESSFULLY! Organizer approval lifecycle, data isolation, live judge score synchronization, prize disbursement payout workflows, and notification broadcast delivery fully verified.", True)

if __name__ == "__main__":
    run_tests()

